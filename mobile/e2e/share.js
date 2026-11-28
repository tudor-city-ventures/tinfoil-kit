// This phone shared on its Wi-Fi, as another phone sees it: nothing without its code, then the listing a kit gives,
// with the book and the map copied from the kit at home, a part of the book, and nothing outside what it lists.
// first-run.yaml runs it once it has copied the code from the Share screen.
/* global maestro, http, json, output -- Maestro's own */
const code = maestro.copiedText.replace(/\D/g, "");
const top = "http://127.0.0.1:8000/data/files";
const ask = (path, headers) =>
  http.get(top + path, { headers: Object.assign({ Authorization: "Bearer " + code }, headers) });
const encode = (path) => path.split("/").map(encodeURIComponent).join("/");

const none = http.get(top);
const wrong = http.get(top, {
  headers: { Authorization: "Bearer " + (code === "12345678" ? "87654321" : "12345678") },
});
const listed = ask("", {});
const listing = listed.status === 200 ? json(listed.body) : { books: [] };
const book = listing.books.find((b) => b.id === "ready.gov_en_all");
const part = book ? ask("/" + encode(book.files[0].path), { Range: "bytes=0-3" }) : { status: 0, body: "" };
const outside = ask("/maps/style/..%2F..%2Fkit.json", {});

const seen = {
  none: none.status,
  wrong: wrong.status,
  listed: listed.status,
  phone: listing.phone,
  books: listing.books.map((b) => b.id),
  map: listing.map ? listing.map.files[0].path : null,
  part: part.status,
  zim: String(part.body).slice(0, 3),
  outside: outside.status,
};
const ok =
  seen.none === 401 &&
  seen.wrong === 401 &&
  seen.listed === 200 &&
  seen.phone === true &&
  !!book &&
  /^maps\/us-alabama-\d{8}\.pmtiles$/.test(seen.map || "") &&
  seen.part === 206 &&
  seen.zim === "ZIM" &&
  seen.outside === 404;
output.shared = ok ? "ok" : JSON.stringify(seen);
