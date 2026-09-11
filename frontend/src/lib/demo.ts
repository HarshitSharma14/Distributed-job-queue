export const demoPassword = "relay-demo-password";

export const demoEmails = {
  Publisher: "publisher.demo@relay.local",
  Producer: "producer.demo@relay.local",
  Worker: "worker.demo@relay.local",
} as const;

const demoEmailSet = new Set<string>(Object.values(demoEmails));

export function isDemoAccount(email?: string): boolean {
  return !!email && demoEmailSet.has(email);
}
