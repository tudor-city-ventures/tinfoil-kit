// What the AI built into the phone is asked: the kit page's instructions and excerpts, so both answer alike
import type { Passage } from "./search";

const SYSTEM =
  "You are the assistant in an offline emergency kit. The internet is down, so the user cannot look anything up. " +
  "Be calm, practical and concise: lead with what to do, use short numbered steps, and give concrete numbers (amounts, times, temperatures) when the excerpts provide them. " +
  "For medical questions, first list the warning signs that mean urgent help is needed, keep any doses conservative, and never invent a dose. " +
  "Never tell the user a wild plant or mushroom is safe to eat based on a description or photo.";

export function prompt(question: string, passages: Passage[]): { instructions: string; prompt: string } {
  const excerpts = passages.map((p, i) => `[${i + 1}] "${p.title}" (${p.bookTitle})\n${p.text}`).join("\n\n");
  return {
    instructions: SYSTEM,
    prompt:
      (passages.length
        ? `Library excerpts:\n\n${excerpts}\n\n`
        : "No library excerpts were found for this question.\n\n") +
      `Question: ${question}\n\n` +
      (passages.length
        ? 'Answer using the excerpts and cite them like [1] or [2]. If they don\'t cover something, say so, then answer from general knowledge and mark that part "(not from the library)".'
        : "Answer from general knowledge and say clearly that it is not from the library."),
  };
}

// The answer as plain words: the phone shows text, not Markdown
export function plain(answer: string): string {
  return answer
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[*-]\s+/gm, "• ")
    .trim();
}
