// Alert notification delivery uses configurable email and push channels.
export function sendAlert(message: string) { return queueNotification(message); }
