<?php
// Seed the Moodle part of SCENARIO.md. Idempotent: run as often as you like.
// Run inside the container as www-data (up.sh does this):
//   php /tmp/fx_seed.php   with env FSTUDENT_PASSWORD FPROF_PASSWORD WW_BASE PL_QUIZ1_URL
// Every seeded activity carries a course-module idnumber "fx-M<n>" so a re-run
// finds it. If its settings drifted (e.g. links.env changed), it is deleted and
// recreated; unchanged ones keep their ids.
define('CLI_SCRIPT', true);
require('/var/www/html/config.php');
require_once($CFG->libdir . '/testing/generator/lib.php');
require_once($CFG->dirroot . '/course/lib.php');
require_once($CFG->dirroot . '/calendar/lib.php');
require_once($CFG->dirroot . '/user/lib.php');

\core\session\manager::set_user(get_admin());
$gen = new testing_data_generator();
$tz = new DateTimeZone('America/Vancouver');
function ts($s) { global $tz; return (new DateTime($s, $tz))->getTimestamp(); }
function env($k) { $v = getenv($k); if ($v === false || $v === '') { fwrite(STDERR, "missing env $k\n"); exit(1); } return $v; }

$ww = rtrim(env('WW_BASE'), '/');
$pl = env('PL_QUIZ1_URL');

// ---- users -------------------------------------------------------------
function ensure_user($gen, $username, $first, $last, $email, $password) {
    global $DB;
    $u = $DB->get_record('user', ['username' => $username, 'deleted' => 0]);
    if (!$u) {
        $u = $gen->create_user(['username' => $username, 'firstname' => $first, 'lastname' => $last,
            'email' => $email, 'password' => $password, 'auth' => 'manual', 'timezone' => 'America/Vancouver']);
        echo "created user $username\n";
    } else {
        update_internal_user_password($u, $password);   // keep in sync with secrets.env
        $DB->update_record('user', (object)['id' => $u->id, 'firstname' => $first, 'lastname' => $last,
            'email' => $email, 'timezone' => 'America/Vancouver', 'suspended' => 0]);
    }
    return $DB->get_record('user', ['id' => $u->id]);
}
$student = ensure_user($gen, 'fstudent', 'Fake', 'Student', 'fstudent@example.invalid', env('FSTUDENT_PASSWORD'));
$prof = ensure_user($gen, 'fprof', 'Fake', 'Professor', 'fprof@example.invalid', env('FPROF_PASSWORD'));

// ---- courses -----------------------------------------------------------
$start = ts('2026-09-01 00:00');
$end = ts('2026-12-31 23:59');
$courses = [
    'MATH100' => ['MATH100-2026W1', 'MATH 100 Differential Calculus'],
    'CPSC121' => ['CPSC121-101-2026W1', 'CPSC 121 101 Models of Computation'],
    'ENGL110' => ['ENGL110-001-2026W1', 'ENGL 110 Approaches to Literature'],
];
$cid = [];
foreach ($courses as $key => [$short, $full]) {
    $c = $DB->get_record('course', ['shortname' => $short]);
    if (!$c) {
        $c = $gen->create_course(['shortname' => $short, 'fullname' => $full, 'startdate' => $start,
            'enddate' => $end, 'numsections' => 3, 'format' => 'topics', 'summary' => "Fake course $short"]);
        echo "created course $short\n";
    } else if ($c->fullname !== $full || (int)$c->startdate !== $start || (int)$c->enddate !== $end) {
        update_course((object)['id' => $c->id, 'fullname' => $full, 'startdate' => $start, 'enddate' => $end]);
    }
    $cid[$key] = (int)$c->id;
    $gen->enrol_user($student->id, $c->id, 'student', 'manual');
    $gen->enrol_user($prof->id, $c->id, 'editingteacher', 'manual');
}

// ---- activities ----------------------------------------------------------
function link_html($url, $text) { return '<p>' . $text . ' <a href="' . s($url) . '">' . s($url) . '</a></p>'; }
$pointer = ['assignsubmission_onlinetext_enabled' => 0, 'assignsubmission_file_enabled' => 0,
            'assignsubmission_comments_enabled' => 0, 'nosubmissions' => 0];
$moodlesub = ['assignsubmission_onlinetext_enabled' => 1, 'assignsubmission_file_enabled' => 0];
$acts = [
    'fx-M1' => ['assign', 'MATH100', 'WeBWorK HW1', ts('2026-09-20 23:59'),
                link_html("$ww/HW1/", 'Do this set on WeBWorK:'), $pointer],
    'fx-M2' => ['assign', 'MATH100', 'Homework 2 (WeBWorK)', ts('2026-09-29 23:00'),
                link_html("$ww/HW2/", 'Homework 2 lives on WeBWorK:'), $pointer],
    'fx-M4' => ['assign', 'MATH100', 'Assignment 1', ts('2026-10-09 23:59'),
                '<p>Written assignment 1. Submit your work here as online text.</p>', $moodlesub],
    'fx-M5' => ['assign', 'CPSC121', 'PrairieLearn Quiz 1', 0,
                link_html($pl, 'Take Quiz 1 on PrairieLearn:'), $pointer],
    'fx-M6' => ['assign', 'ENGL110', 'Assignment 1', ts('2026-10-09 23:59'),
                '<p>Close reading response. Submit as online text.</p>', $moodlesub],
    'fx-M8' => ['assign', 'CPSC121', 'Quiz 3', ts('2026-10-16 23:59'),
                '<p>Quiz 3 is a written quiz submitted on Moodle.</p>', $moodlesub],
    'fx-M9' => ['page', 'ENGL110', 'Reading: Chapter 4', 0,
                '<p>Read chapter 4 of the course reader before next week.</p>', []],
];

function current_matches($cm, $mod, $course, $name, $due, $intro, $extra) {
    global $DB;
    if ((int)$cm->course !== $course) return false;
    $inst = $DB->get_record($mod, ['id' => $cm->instance]);
    if (!$inst || $inst->name !== $name) return false;
    if ($mod === 'assign') {
        if ((int)$inst->duedate !== $due || $inst->intro !== $intro || (int)$inst->allowsubmissionsfromdate !== 0) return false;
        $on = $DB->get_field('assign_plugin_config', 'value', ['assignment' => $inst->id,
            'plugin' => 'onlinetext', 'subtype' => 'assignsubmission', 'name' => 'enabled']);
        if ((int)$on !== (int)$extra['assignsubmission_onlinetext_enabled']) return false;
    } else if ($inst->content !== $intro) {
        return false;
    }
    return true;
}

foreach ($acts as $idn => [$mod, $ckey, $name, $due, $intro, $extra]) {
    $course = $cid[$ckey];
    $cm = $DB->get_record_sql("SELECT cm.* FROM {course_modules} cm JOIN {modules} m ON m.id = cm.module
                                WHERE cm.idnumber = ? AND m.name = ? AND cm.deletioninprogress = 0", [$idn, $mod]);
    if ($cm && current_matches($cm, $mod, $course, $name, $due, $intro, $extra)) continue;
    if ($cm) { course_delete_module($cm->id, false); echo "recreating $idn\n"; }
    $rec = ['course' => $course, 'name' => $name, 'idnumber' => $idn, 'section' => 1];
    if ($mod === 'assign') {
        $rec += ['intro' => $intro, 'introformat' => FORMAT_HTML, 'duedate' => $due,
                 'allowsubmissionsfromdate' => 0, 'cutoffdate' => 0, 'gradingduedate' => 0,
                 'alwaysshowdescription' => 1] + $extra;
    } else {
        $rec += ['intro' => '', 'content' => $intro, 'contentformat' => FORMAT_HTML];
    }
    $gen->create_module($mod, $rec);
    echo "created $idn $mod \"$name\"\n";
}

// ---- course calendar events -----------------------------------------------
$events = [
    ['MATH100', 'Midterm 1', ts('2026-10-15 18:00'), 5400, '<p>In-class midterm, room TBA.</p>'],
    ['CPSC121', 'Problem Set 3 due', ts('2026-10-05 17:00'), 0, '<p>Reminder: Problem Set 3 is due.</p>'],
];
foreach ($events as [$ckey, $name, $start, $dur, $desc]) {
    $course = $cid[$ckey];
    $ev = $DB->get_records('event', ['courseid' => $course, 'name' => $name, 'eventtype' => 'course']);
    $keep = null;
    foreach ($ev as $e) {
        if (!$keep && (int)$e->timestart === $start && (int)$e->timeduration === $dur && $e->description === $desc) {
            $keep = $e;
        } else {
            calendar_event::load($e->id)->delete();   // drift or duplicate
        }
    }
    if ($keep) continue;
    calendar_event::create((object)['name' => $name, 'description' => $desc, 'format' => FORMAT_HTML,
        'courseid' => $course, 'groupid' => 0, 'userid' => $prof->id, 'modulename' => '', 'instance' => 0,
        'eventtype' => 'course', 'timestart' => $start, 'timeduration' => $dur, 'visible' => 1], false);
    echo "created event \"$name\"\n";
}

foreach ($cid as $c) rebuild_course_cache($c, true);
echo "seed ok\n";
