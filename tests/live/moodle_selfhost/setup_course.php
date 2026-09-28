<?php
// Seeds the disposable FAKE101 course for lauds-cli's Moodle live-oracle
// capture. Not part of Moodle core: copy into the moodle-oracle-web
// container's docroot and run with `php setup_course.php` (see this
// directory's README). Idempotent - safe to re-run after a partial failure.
//
// Uses Moodle's own documented pattern for getting a data generator outside
// PHPUnit (see admin/tool/generator/classes/course_backend.php, which core
// itself uses this same way): require lib/phpunit/classes/util.php, then
// phpunit_util::get_data_generator().
define('CLI_SCRIPT', true);
define('NO_OUTPUT_BUFFERING', true);

require(__DIR__ . '/config.php');
require_once($CFG->libdir . '/clilib.php');
require_once($CFG->dirroot . '/lib/phpunit/classes/util.php');
require_once($CFG->dirroot . '/mod/assign/locallib.php');
require_once($CFG->dirroot . '/mod/assign/lib.php');
require_once($CFG->dirroot . '/course/lib.php');

global $DB, $CFG;

$studentuser = getenv('MOODLE_STUDENT_USER') ?: 'fakestudent';
$studentpass = getenv('MOODLE_STUDENT_PASSWORD');
$teacheruser = getenv('MOODLE_TEACHER_USER') ?: 'fakeprof';
$teacherpass = getenv('MOODLE_TEACHER_PASSWORD');
if (!$studentpass || !$teacherpass) {
    cli_error('MOODLE_STUDENT_PASSWORD / MOODLE_TEACHER_PASSWORD must be set in the environment');
}

$generator = phpunit_util::get_data_generator();

function vts($str) {
    return (new DateTime($str, new DateTimeZone('America/Vancouver')))->getTimestamp();
}

// --- Course (idempotent) -------------------------------------------------
$course = $DB->get_record('course', ['shortname' => 'FAKE101']);
if (!$course) {
    $course = $generator->create_course([
        'shortname' => 'FAKE101',
        'fullname'  => 'Fake Course 101 (Moodle live oracle)',
        'summary'   => 'Disposable test course for lauds-cli oracle capture. Not real.',
        'startdate' => vts('2026-09-01 00:00:00'),
    ]);
    mtrace("created course id={$course->id}");
} else {
    mtrace("course already exists id={$course->id}");
}

// --- Users (idempotent) ---------------------------------------------------
$teacher = $DB->get_record('user', ['username' => $teacheruser]);
if (!$teacher) {
    $teacher = $generator->create_user([
        'username' => $teacheruser, 'password' => $teacherpass,
        'firstname' => 'Fake', 'lastname' => 'Prof', 'email' => $teacheruser . '@example.invalid',
    ]);
}
$student = $DB->get_record('user', ['username' => $studentuser]);
if (!$student) {
    $student = $generator->create_user([
        'username' => $studentuser, 'password' => $studentpass,
        'firstname' => 'Fake', 'lastname' => 'Student', 'email' => $studentuser . '@example.invalid',
    ]);
}
if (!$DB->record_exists('role_assignments', [])) {
    // (cheap existence check skipped - enrol_user() is itself idempotent-ish
    // via enrol plugin, but guard on the enrolment table directly instead.)
}
$enrolled = $DB->record_exists_sql(
    "SELECT 1 FROM {user_enrolments} ue JOIN {enrol} e ON e.id = ue.enrolid
     WHERE e.courseid = :cid AND ue.userid = :uid",
    ['cid' => $course->id, 'uid' => $student->id]
);
if (!$enrolled) {
    $generator->enrol_user($teacher->id, $course->id, 'editingteacher');
    $generator->enrol_user($student->id, $course->id, 'student');
    mtrace('enrolled teacher + student');
} else {
    mtrace('already enrolled');
}

// --- Assignments: the edge cases from tests/live/README.md's table --------
// (past-due, due-soon, due-after-2027-01-06, not-yet-open, no-due-date,
// a Vancouver-midnight due time, and a submitted+graded one; plus one quiz.)
function ensure_assign($generator, $course, $name, $duedate, $allowfrom) {
    global $DB;
    $existing = $DB->get_record('assign', ['course' => $course->id, 'name' => $name]);
    if ($existing) {
        return $existing;
    }
    $assigngen = $generator->get_plugin_generator('mod_assign');
    return $assigngen->create_instance([
        'course' => $course->id, 'name' => $name,
        'duedate' => $duedate, 'allowsubmissionsfromdate' => $allowfrom,
    ]);
}

$a1 = ensure_assign($generator, $course, 'FAKE_A1_Past_Due', vts('2026-09-20 23:59:00'), vts('2026-09-01 00:00:00'));
$a2 = ensure_assign($generator, $course, 'FAKE_A2_Due_Soon', time() + 36 * 3600, vts('2026-09-15 00:00:00'));
$a3 = ensure_assign($generator, $course, 'FAKE_A3_January_2027', vts('2027-01-15 23:59:00'), vts('2026-09-15 00:00:00'));
$a4 = ensure_assign($generator, $course, 'FAKE_A4_Not_Yet_Open', vts('2026-10-22 23:59:00'), vts('2026-10-15 00:00:00'));
$a5 = ensure_assign($generator, $course, 'FAKE_A5_No_Due_Date', 0, vts('2026-09-01 00:00:00'));
$a6 = ensure_assign($generator, $course, 'FAKE_A6_Vancouver_Midnight', vts('2026-09-30 00:00:00'), vts('2026-09-01 00:00:00'));
$a7 = ensure_assign($generator, $course, 'FAKE_A7_Submitted_Graded', vts('2026-09-10 23:59:00'), vts('2026-09-01 00:00:00'));
mtrace('assignments ready: ' . implode(',', [$a1->id, $a2->id, $a3->id, $a4->id, $a5->id, $a6->id, $a7->id]));

// a7: submit as the student, then grade as the teacher.
$cm7 = get_coursemodule_from_instance('assign', $a7->id, $course->id);
$sub = $DB->get_record('assign_submission', ['assignment' => $a7->id, 'userid' => $student->id]);
if (!$sub) {
    $assigngen = $generator->get_plugin_generator('mod_assign');
    $assigngen->create_submission([
        'cmid' => $cm7->id, 'userid' => $student->id,
        'onlinetext' => ['text' => 'Fake submission text for the oracle capture.', 'format' => FORMAT_PLAIN],
    ]);
    $sub = $DB->get_record('assign_submission', ['assignment' => $a7->id, 'userid' => $student->id]);
}
if ($sub && $sub->status !== 'submitted') {
    // ponytail: the generator's create_submission() leaves status "new" on
    // this checkout instead of the requested "submitted" - written directly
    // rather than chasing the plugin's own submission-status logic, since
    // this is disposable fixture data, not something a future adapter reads.
    $sub->status = 'submitted';
    $sub->timemodified = time();
    $DB->update_record('assign_submission', $sub);
    mtrace('submission -> submitted');
}
if (!$DB->record_exists('assign_grades', ['assignment' => $a7->id, 'userid' => $student->id])) {
    // Written directly to assign_grades + assign_update_grades(), not via
    // assign::save_grade(): that path calls get_user_grade() ->
    // get_user_submission(create=true), which on this checkout inserts a
    // second submission row with a NULL attemptnumber (a pre-existing
    // Moodle core bug on this version, not something this seed script
    // should paper over by faking a different code path) and aborts the
    // transaction. assign_update_grades() is the same documented,
    // version-independent function mod/assign/lib.php itself uses to push
    // an assign_grades row into the gradebook, and it doesn't hit that path.
    $gradeobj = new stdClass();
    $gradeobj->assignment = $a7->id;
    $gradeobj->userid = $student->id;
    $gradeobj->grader = $teacher->id;
    $gradeobj->timecreated = time();
    $gradeobj->timemodified = time();
    $gradeobj->grade = 95.0;
    $gradeobj->attemptnumber = 0;
    $DB->insert_record('assign_grades', $gradeobj);
    $assign7full = $DB->get_record('assign', ['id' => $a7->id]);
    assign_update_grades($assign7full, $student->id);
    mtrace('graded a7 -> 95.0');
}

// --- Quiz -------------------------------------------------------------
$q1 = $DB->get_record('quiz', ['course' => $course->id, 'name' => 'FAKE_Q1_Quiz']);
if (!$q1) {
    $quizgen = $generator->get_plugin_generator('mod_quiz');
    $q1 = $quizgen->create_instance([
        'course' => $course->id, 'name' => 'FAKE_Q1_Quiz',
        'timeopen' => vts('2026-09-15 00:00:00'),
        'timeclose' => vts('2026-10-05 23:59:00'),
    ]);
    mtrace("created quiz id={$q1->id}");
} else {
    mtrace("quiz already exists id={$q1->id}");
}

mtrace('SETUP_OK');
