// The AI built into the phone (modules/kit-files), or the testing menu's stand-in for it
import * as phone from "../../modules/kit-files";
import type { AIState } from "../../modules/kit-files";
import { FAILED, fake, faked } from "@/kit/qa";

export type { AIState };

export const PRETEND =
  "A pretend answer from the testing menu, in place of the phone's AI, to show how an answer looks. The phone's own " +
  "AI writes its answer from the passages below.";

const later = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));

export async function aiState(): Promise<AIState> {
  const f = faked().ai;
  if (!f) return phone.aiState();
  return f === "failing" ? "ready" : f;
}

export async function aiDownload(cellular: boolean): Promise<void> {
  if (!faked().ai) return phone.aiDownload(cellular);
  await later(3000);
  fake({ ai: "ready" });
}

export async function aiAnswer(instructions: string, prompt: string): Promise<string> {
  const f = faked().ai;
  if (!f) return phone.aiAnswer(instructions, prompt);
  await later(2000);
  if (f === "failing") throw new Error(FAILED);
  return PRETEND;
}
