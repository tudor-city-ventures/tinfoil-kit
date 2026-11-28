import { expect, test } from "@jest/globals";

import { plain, prompt } from "./answer";

test("the AI is asked as the kit page asks it, with the excerpts numbered", () => {
  const p = prompt("How do I purify water?", [
    { book: "b", bookTitle: "Survival guide", title: "Water purification", page: "/W", text: "Boil it." },
  ]);
  expect(p.instructions).toContain("never invent a dose");
  expect(p.prompt).toBe(
    'Library excerpts:\n\n[1] "Water purification" (Survival guide)\nBoil it.\n\nQuestion: How do I purify water?\n\n' +
      'Answer using the excerpts and cite them like [1] or [2]. If they don\'t cover something, say so, then answer from general knowledge and mark that part "(not from the library)".',
  );
  expect(prompt("Why is the sky blue?", []).prompt).toContain("say clearly that it is not from the library");
});

test("its answer as plain words", () => {
  expect(plain("## Steps\n**Boil** water.\n- Let it cool\n* Store it\n")).toBe(
    "Steps\nBoil water.\n• Let it cool\n• Store it",
  );
});
