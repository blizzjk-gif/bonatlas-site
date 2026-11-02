import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtemp,
  mkdir,
  readFile,
  writeFile,
  rm,
  stat,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, dirname, basename } from "node:path";
import { syncCatalog } from "../scripts/sync-bon-plot.mjs";

const json = (value) => `${JSON.stringify(value, null, 2)}\n`;
const hash = (value) => createHash("sha256").update(value).digest("hex");
function feed(revision = 1, approved = true) {
  const content = {
    schemaVersion: 1,
    id: "bon-plot",
    revision,
    updatedAt: "2026-11-02",
    product: {
      name: "Bon Plot",
      tagline: "Программа для автора",
      description: "Искусственный тест.",
      audiences: ["Авторы"],
      platforms: ["Windows"],
      website: "https://bonatlas.ru/plot/",
    },
    release: {
      latestPublished: "0.1.3",
    },
    workflows: [],
    limitations: ["AI ошибается."],
    features: [
      {
        id: "book-editor",
        title: "Книга",
        availability: "released",
        verifiedInRelease: "0.1.3",
        description: `Редакция ${revision}.`,
        benefit: "Писать по главам.",
        howTo: ["Откройте книгу."],
        requirements: [],
        limitations: ["Сохраняйте резервные копии."],
      },
    ],
  };
  const contentHash = hash(json(content));
  return {
    ...content,
    publication: {
      status: approved ? "approved" : "draft",
      approvedContentHash: approved ? contentHash : null,
      contentHash,
    },
  };
}
async function source(directory, value) {
  const root = join(directory, "source");
  const path = join(root, "docs/product/generated");
  await mkdir(path, { recursive: true });
  const files = {
    "bon-plot.json": json(value),
    "bon-plot.md": "# Искусственный паспорт\n",
  };
  const manifest = {
    schemaVersion: 1,
    productId: "bon-plot",
    contentHash: value.publication.contentHash,
    files: Object.fromEntries(
      Object.entries(files).map(([name, text]) => [name, hash(text)]),
    ),
  };
  for (const [name, text] of Object.entries({
    ...files,
    "manifest.json": json(manifest),
  }))
    await writeFile(join(path, name), text, "utf8");
  return root;
}
async function isolated(work) {
  const directory = await mkdtemp(join(tmpdir(), "bon-product-sync-"));
  try {
    await work(directory, join(directory, "site"));
  } finally {
    assert.equal(dirname(resolve(directory)), resolve(tmpdir()));
    assert(basename(directory).startsWith("bon-product-sync-"));
    await rm(directory, { recursive: true, force: true });
  }
}

test("rejects private plans even in a correctly hashed and approved package", () =>
  isolated(async (directory, site) => {
    const value = feed();
    value.features[0].availability = "planned";
    value.features[0].verifiedInRelease = null;
    const { publication, ...content } = value;
    publication.contentHash = hash(json(content));
    publication.approvedContentHash = publication.contentHash;
    await assert.rejects(
      syncCatalog(await source(directory, value), site),
      /Non-public feature rejected/,
    );
    await assert.rejects(stat(site), /ENOENT/);
  }));

test("copies only approved facts, prepares a review and does not rewrite unchanged files", () =>
  isolated(async (directory, site) => {
    const root = await source(directory, feed());
    assert.deepEqual((await syncCatalog(root, site)).changed, true);
    const target = join(site, "public/product-info/bon-plot.json");
    const before = (await stat(target)).mtimeMs;
    assert.equal((await syncCatalog(root, site)).changed, false);
    assert.equal((await stat(target)).mtimeMs, before);
    assert.match(
      await readFile(
        join(site, "editorial/product-updates/bon-plot.md"),
        "utf8",
      ),
      /Публикация рекламных текстов и статей.*не разрешена/,
    );
    await assert.rejects(
      stat(join(site, "src/content/site/plot.json")),
      /ENOENT/,
    );
  }));

test("draft cannot replace public data; review mode can prepare an internal preview", () =>
  isolated(async (directory, site) => {
    await syncCatalog(await source(directory, feed()), site);
    const target = join(site, "public/product-info/bon-plot.json");
    const before = await readFile(target, "utf8");
    const root = await source(directory, feed(2, false));
    assert.equal((await syncCatalog(root, site)).approved, false);
    await syncCatalog(root, site, "review");
    assert.equal(await readFile(target, "utf8"), before);
    assert.match(
      await readFile(
        join(site, "editorial/product-updates/bon-plot.md"),
        "utf8",
      ),
      /Утверждение: draft/,
    );
  }));

test("check mode writes no website files", () =>
  isolated(async (directory, site) => {
    assert.equal(
      (await syncCatalog(await source(directory, feed()), site, "check"))
        .changed,
      true,
    );
    await assert.rejects(stat(site), /ENOENT/);
  }));

test("damaged package is rejected before any output", () =>
  isolated(async (directory, site) => {
    const root = await source(directory, feed());
    await writeFile(
      join(root, "docs/product/generated/bon-plot.md"),
      "damaged",
    );
    await assert.rejects(syncCatalog(root, site), /Broken catalog package/);
    await assert.rejects(stat(site), /ENOENT/);
  }));

test("rejects stale approval even with a recomputed package manifest", () =>
  isolated(async (directory, site) => {
    const value = feed();
    value.features[0].description = "Неутверждённый факт.";
    await assert.rejects(
      syncCatalog(await source(directory, value), site),
      /content hash mismatch/,
    );
  }));

test("rejects rollback and changed facts without a revision bump", () =>
  isolated(async (directory, site) => {
    await syncCatalog(await source(directory, feed(2)), site);
    await assert.rejects(
      syncCatalog(await source(directory, feed(1)), site),
      /revision rollback/,
    );
    const value = feed(2);
    value.features[0].title = "Изменённое название";
    const { publication, ...content } = value;
    publication.contentHash = hash(json(content));
    publication.approvedContentHash = publication.contentHash;
    await assert.rejects(
      syncCatalog(await source(directory, value), site),
      /Increment catalog revision/,
    );
  }));

test("rejects extra private fields and future release claims", () =>
  isolated(async (directory, site) => {
    const value = feed();
    value.features[0].evidence = ["private"];
    const { publication, ...content } = value;
    publication.contentHash = hash(json(content));
    publication.approvedContentHash = publication.contentHash;
    await assert.rejects(
      syncCatalog(await source(directory, value), site),
      /Unexpected public fields/,
    );
    const future = feed();
    future.features[0].verifiedInRelease = "0.1.5";
    const { publication: next, ...nextContent } = future;
    next.contentHash = hash(json(nextContent));
    next.approvedContentHash = next.contentHash;
    await assert.rejects(syncCatalog(await source(directory, future), site));
  }));
