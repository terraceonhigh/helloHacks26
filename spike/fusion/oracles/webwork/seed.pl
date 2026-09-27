# Seed the WeBWorK part of SCENARIO.md into course math100_2026w1.
# Run via:  bin/wwsh math100_2026w1 /fx-seed/seed.pl   (seed.sh does this)
# $ce and $db are provided by wwsh. Passwords come from the environment
# (FSTUDENT_PASSWORD, FPROF_PASSWORD) and are never printed.
# Idempotent: users are upserted, the four scenario sets are deleted and
# re-imported from their .def files, so dates always match SCENARIO.md exactly.
use lib "$ENV{PG_ROOT}/lib";    # WeBWorK::Utils::Sets needs PG modules (wwsh only adds webwork2/lib)
use strict;
use warnings;
our ($ce, $db);    # provided by wwsh (package main)
use WeBWorK::Utils                   qw(cryptPassword);
use WeBWorK::File::SetDef            qw(importSetsFromDef);

my @users = (
	{ user_id => 'fstudent', first_name => 'Fake', last_name => 'Student', email_address => 'fstudent@example.invalid',
	  student_id => 'fstudent', perm => 0,  pw => $ENV{FSTUDENT_PASSWORD} },
	{ user_id => 'fprof', first_name => 'Fake', last_name => 'Professor', email_address => 'fprof@example.invalid',
	  student_id => 'fprof', perm => 10, pw => $ENV{FPROF_PASSWORD} },
);

for my $u (@users) {
	die "missing password for $u->{user_id}\n" unless $u->{pw};
	my $rec = $db->existsUser($u->{user_id}) ? $db->getUser($u->{user_id}) : $db->newUser(user_id => $u->{user_id});
	$rec->$_($u->{$_}) for qw(first_name last_name email_address student_id);
	$rec->status('C');
	$rec->section('');
	$rec->recitation('');
	$rec->comment('fake fusion-spike user');
	$db->existsUser($u->{user_id}) ? $db->putUser($rec) : $db->addUser($rec);

	my $pw = $db->existsPassword($u->{user_id}) ? $db->getPassword($u->{user_id}) : $db->newPassword(user_id => $u->{user_id});
	$pw->password(cryptPassword($u->{pw}));
	$pw->otp_secret(undef);
	$db->existsPassword($u->{user_id}) ? $db->putPassword($pw) : $db->addPassword($pw);

	my $pl = $db->getPermissionLevel($u->{user_id});
	if ($pl) { $pl->permission($u->{perm}); $db->putPermissionLevel($pl) }
	else { $db->addPermissionLevel($db->newPermissionLevel(user_id => $u->{user_id}, permission => $u->{perm})) }
	print "user $u->{user_id} ok (permission $u->{perm})\n";
}

my @sets = qw(HW1 HW2 HW9 HW3);
for my $set (@sets) {
	$db->deleteGlobalSet($set) if $db->existsGlobalSet($set);
}
my ($added, $skipped, $errors) = importSetsFromDef($ce, $db, [ map {"set$_.def"} @sets ], undef, 'all');
print "sets added: @$added\n";
print "sets skipped: @$skipped\n" if @$skipped;
if (@$errors) { print "set import error: @$_\n" for @$errors; die "set import failed\n" }
die "expected 4 sets, got " . scalar(@$added) . "\n" unless @$added == 4;
