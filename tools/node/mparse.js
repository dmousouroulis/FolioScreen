// Parses Power Query M expressions with Microsoft's @microsoft/powerquery-parser.
// Usage: node tools/mparse.js file1.m file2.m ...   (prints OK/FAIL per file, exit 1 on any failure)
const fs = require("fs");
const PQP = require("@microsoft/powerquery-parser");
(async () => {
  let failed = 0;
  for (const f of process.argv.slice(2)) {
    const text = fs.readFileSync(f, "utf8");
    const res = await PQP.TaskUtils.tryLexParse(PQP.DefaultSettings, text);
    if (PQP.TaskUtils.isParseStageOk(res)) {
      console.log("OK   " + f);
    } else {
      failed++;
      const err = res.error ? (res.error.message || String(res.error)) : "unknown";
      console.log("FAIL " + f + " :: " + err.slice(0, 300));
    }
  }
  process.exit(failed ? 1 : 0);
})();
