// The kit builder's data files, fetched once however many parts of the page ask for them.
const loads = {};

export function loadJSON(file) {
  if (!loads[file]) {
    loads[file] = fetch("/" + file).then((r) => {
      if (!r.ok) throw new Error(`${file}: ${r.status}`);
      return r.json();
    });
    loads[file].catch(() => delete loads[file]); // so a later ask tries again
  }
  return loads[file];
}
