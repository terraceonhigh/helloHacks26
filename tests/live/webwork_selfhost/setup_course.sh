#!/usr/bin/env bash
# Runs INSIDE webwork-app as www-data (see ~/webwork/README-oracle.txt).
# Creates the FAKE course fake101 with WeBWorK's own tools: bin/addcourse
# (classlist with crypted passwords) and WeBWorK::File::SetDef::importSetsFromDef
# (the same code path as Instructor Tools > Sets Manager > Import).
# Passwords arrive as env vars by name only; nothing secret is printed.
set -euo pipefail
cd /opt/webwork/webwork2
C=/opt/webwork/courses/fake101
PROBLEM=${WW_PROBLEM:-Library/Rochester/set0/prob1.pg}

# 0) Site admin course: replace the entrypoint's default admin/admin password.
perl -Ilib -I/opt/webwork/pg/lib -MWeBWorK::CourseEnvironment -MWeBWorK::DB -MWeBWorK::Utils=cryptPassword -e '
  my $ce = WeBWorK::CourseEnvironment->new({courseName => "admin"});
  my $db = WeBWorK::DB->new($ce);
  my $p = $db->getPassword("admin") or die "no admin password record\n";
  $p->password(cryptPassword($ENV{WW_SITE_ADMIN_PASSWORD})); $db->putPassword($p);
  print "admin course: admin password rotated\n";'

# 0b) The image's entrypoint creates the admin course on a fresh DB but only
# runs upgrade_admin_db.pl when admin tables are missing, so the site-wide
# lti_course_map table never gets created and bin/delcourse fails. Upgrade once.
bin/upgrade_admin_db.pl | tail -1

# 1) Course + users (templates copied from modelCourse, like the web Add Course
# form does, so templates/Library -> the OPL exists)
if [ ! -d "$C" ]; then
  umask 077
  LST=$(mktemp /tmp/fake101.XXXXXX.lst)
  perl -Ilib -I/opt/webwork/pg/lib -MWeBWorK::Utils=cryptPassword -e '
    print "# Field order: student_id,last_name,first_name,status,comment,section,recitation,email_address,user_id,crypted_password,permission\n";
    printf "F0000001,Professor,Fake,C,,,,fakeprof\@example.invalid,%s,%s,10\n", $ENV{WW_INSTRUCTOR_USER}, cryptPassword($ENV{WW_INSTRUCTOR_PASSWORD});
    printf "F0000002,Student,Fake,C,,001,,fakestudent\@example.invalid,%s,%s,0\n", $ENV{WW_STUDENT_USER}, cryptPassword($ENV{WW_STUDENT_PASSWORD});
  ' > "$LST"
  umask 002
  bin/addcourse fake101 --templates-from=modelCourse --users="$LST" --professors="$WW_INSTRUCTOR_USER"
  rm -f "$LST"
  # Explicit course timezone, and non-Secure cookies: defaults.config has
  # $CookieSecure = 1 (HTTPS assumed); this oracle is plain HTTP on the tailnet,
  # where a Secure session cookie is never sent back and login loops.
  printf '\n# oracle\n$siteDefaults{timezone} = "America/Vancouver";\n$CookieSecure = 0;\n' >> "$C/course.conf"
  echo "course fake101 created"
else
  echo "course fake101 exists; (re)importing only missing sets"
fi

# 2) Set definition files (dates are course-local, America/Vancouver)
mkset() { # id open due answer description
  cat > "$C/templates/set$1.def" <<DEF
assignmentType          = default
openDate                = $2
dueDate                 = $3
answerDate              = $4
enableReducedScoring    = N
paperHeaderFile         = defaultHeader
screenHeaderFile        = defaultHeader
description             = $5

problemListV2
problem_start
problem_id           = 1
source_file          = $PROBLEM
value                = 1
max_attempts         = -1
problem_end
DEF
}
mkset FAKE_HW1_Past_Due     "09/01/2026 at 12:00am" "09/20/2026 at 11:59pm" "09/21/2026 at 11:59pm" "FAKE oracle set: past due"
mkset FAKE_HW2_Due_Soon     "09/15/2026 at 12:00am" "09/28/2026 at 05:00pm" "09/29/2026 at 05:00pm" "FAKE oracle set: due within 48h of setup (2026-09-26)"
mkset FAKE_HW3_January_2027 "09/15/2026 at 12:00am" "01/15/2027 at 11:59pm" "01/16/2027 at 11:59pm" "FAKE oracle set: due after 2027-01-06"
mkset FAKE_HW4_Not_Yet_Open "10/15/2026 at 12:00am" "10/22/2026 at 11:59pm" "10/23/2026 at 11:59pm" "FAKE oracle set: not open yet"
mkset FAKE_HW5_Far_Future   "09/01/2026 at 12:00am" "12/31/2099 at 11:59pm" "12/31/2099 at 11:59pm" "FAKE oracle set: WeBWorK requires dates, so a far-future due date stands in for none"

perl -Ilib -I/opt/webwork/pg/lib -MWeBWorK::CourseEnvironment -MWeBWorK::DB -MWeBWorK::File::SetDef=importSetsFromDef -e '
  my $ce = WeBWorK::CourseEnvironment->new({courseName => "fake101"});
  my $db = WeBWorK::DB->new($ce);
  my @f = map { "setFAKE_HW$_.def" } qw(1_Past_Due 2_Due_Soon 3_January_2027 4_Not_Yet_Open 5_Far_Future);
  my ($added, $skipped, $errors) = importSetsFromDef($ce, $db, \@f, undef, "all");
  print "added: @$added\nskipped: @$skipped\n";
  print "error: ", (ref $_ ? "@$_" : $_), "\n" for grep { !(ref $_ && $_->[0] =~ /already exists/) } @$errors;
  for my $s (sort $db->listGlobalSets) { my $r = $db->getGlobalSet($s);
    printf "%-24s open=%d due=%d answer=%d visible=%d users=%d\n", $s, $r->open_date, $r->due_date, $r->answer_date, $r->visible, scalar $db->listSetUsers($s); }'

# 3) Two-factor auth is ON by default for password courses (defaults.config
# $twoFA{enabled} = 1). Keep it on, and pre-provision each fake user's TOTP
# secret (raw HMAC key, as WeBWorK::Utils::TOTP stores it) from secrets.env so
# a script can compute codes instead of scanning a QR code.
perl -Ilib -I/opt/webwork/pg/lib -MWeBWorK::CourseEnvironment -MWeBWorK::DB -e '
  my $ce = WeBWorK::CourseEnvironment->new({courseName => "fake101"});
  my $db = WeBWorK::DB->new($ce);
  for (["WW_INSTRUCTOR_USER","WW_INSTRUCTOR_OTP_SECRET"], ["WW_STUDENT_USER","WW_STUDENT_OTP_SECRET"]) {
    my $p = $db->getPassword($ENV{$_->[0]}) or die "no password record\n";
    $p->otp_secret($ENV{$_->[1]}); $db->putPassword($p); print "otp secret set for $ENV{$_->[0]}\n"; }'
