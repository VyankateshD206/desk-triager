// Optional developer tool: npm install --no-save playwright; npx playwright install chromium.
import { createRequire } from "node:module";
import { mkdir, rename } from "node:fs/promises";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const output = process.env.DEMO_OUTPUT || "/tmp/desk-demo";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 },
  recordVideo: { dir: output, size: { width: 1440, height: 1080 } } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
try {
  await page.goto(process.env.DEMO_URL || "http://127.0.0.1:18080");
  if (!process.env.DEMO_TOKEN) throw Error("Set DEMO_TOKEN to the isolated server token");
  await page.locator("#token").fill(process.env.DEMO_TOKEN);
  await page.locator("#token").press("Tab");
  await page.locator("#inject").waitFor();
  await page.waitForTimeout(1500);
  await page.locator("select").first().selectOption("rate_limit|execution-gateway");
  await page.locator("#inject").click();
  const review = page.locator("#incident-rows button").first();
  await review.waitFor({ timeout: 15000 });
  await page.waitForTimeout(2500);
  await review.click();
  await page.locator("#detail").waitFor();
  await page.locator("#investigation-trace").locator("..").locator("summary").first().click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: output + "/incident-review.png" });
  await page.locator("#approve").click();
  await page.locator("#modal-message").filter({ hasText: /queued/i }).waitFor();
  await page.waitForTimeout(3000);
  await page.locator("#close").click();
  await page.locator("#show-history").check();
  await page.locator("#scenario-hint").filter({ hasText: /^Recovered/ }).waitFor({ timeout: 15000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: output + "/recovered.png" });
  if (errors.length) throw Error(errors.join("\n"));
  const video = page.video();
  await context.close();
  await rename(await video.path(), output + "/desk-demo.webm");
  console.log("Verified review/approval flow; saved video and screenshots to " + output);
} finally {
  await browser.close();
}
