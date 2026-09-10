/**
 * Reminders - EchoNotes Feature 5.
 *
 * Due and upcoming reminders, each linked back to the note it came from. Due dates are spoken the
 * way a person would say them ("tomorrow at four"), not as ISO strings.
 *
 * Contact actions are offered as buttons that ask for confirmation. EchoNotes never places a call
 * or sends a message on its own: an accidental outbound message cannot be taken back, and cannot
 * be spotted by glancing at the screen.
 */

export interface ReminderListProps {
  withinHours?: number;
}

export function ReminderList(_props: ReminderListProps) {
  throw new Error("not implemented");
}
