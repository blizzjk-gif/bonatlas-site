import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const hash = (value) => createHash("sha256").update(value).digest("hex");
const json = (value) => `${JSON.stringify(value, null, 2)}\n`;
function keys(value, expected) {
  assert(value && typeof value === "object" && !Array.isArray(value));
  assert.deepEqual(
    Object.keys(value).sort(),
    expected.split(" ").sort(),
    "Unexpected public fields",
  );
}

export function validatePublicFeed(feed, manifest, files) {
  keys(manifest, "schemaVersion productId contentHash files");
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.productId, "bon-plot");
  keys(manifest.files, "bon-plot.json bon-plot.md");
  for (const name of ["bon-plot.json", "bon-plot.md"]) {
    assert.equal(
      hash(files[name]),
      manifest.files[name],
      `Broken catalog package: ${name}`,
    );
  }
  keys(
    feed,
    "schemaVersion id revision updatedAt product release workflows limitations features publication",
  );
  assert.equal(feed.schemaVersion, 1, "Unsupported feed version");
  assert.equal(feed.id, "bon-plot");
  assert(Number.isSafeInteger(feed.revision) && feed.revision > 0);
  assert(/^\d{4}-\d{2}-\d{2}$/.test(feed.updatedAt));
  keys(feed.publication, "status approvedContentHash contentHash");
  assert(["draft", "approved"].includes(feed.publication.status));
  const { publication, ...content } = feed;
  assert.equal(
    hash(json(content)),
    publication.contentHash,
    "Catalog content hash mismatch",
  );
  assert.equal(manifest.contentHash, publication.contentHash);
  if (publication.status === "approved")
    assert.equal(
      publication.approvedContentHash,
      publication.contentHash,
      "Unapproved content",
    );
  keys(feed.product, "name tagline description audiences platforms website");
  const text = (value) =>
    assert(typeof value === "string" && value.trim(), "Expected public text");
  const strings = (value) => {
    assert(Array.isArray(value) && value.length <= 64);
    value.forEach(text);
  };
  for (const name of ["name", "tagline", "description", "website"])
    text(feed.product[name]);
  strings(feed.product.audiences);
  strings(feed.product.platforms);
  strings(feed.workflows);
  strings(feed.limitations);
  assert.equal(feed.product.website, "https://bonatlas.ru/plot/");
  keys(feed.release, "latestPublished");
  assert(/^\d+\.\d+\.\d+$/.test(feed.release.latestPublished));
  assert(
    Array.isArray(feed.features) &&
      feed.features.length > 0 &&
      feed.features.length <= 100,
  );
  const ids = new Set();
  for (const feature of feed.features) {
    keys(
      feature,
      "id title availability verifiedInRelease description benefit howTo requirements limitations",
    );
    assert(/^[a-z][a-z0-9-]{1,70}$/.test(feature.id) && !ids.has(feature.id));
    ids.add(feature.id);
    assert.equal(
      feature.availability,
      "released",
      "Non-public feature rejected",
    );
    assert(/^\d+\.\d+\.\d+$/.test(feature.verifiedInRelease));
    assert(
      feature.verifiedInRelease.localeCompare(
        feed.release.latestPublished,
        undefined,
        { numeric: true },
      ) <= 0,
    );
    for (const name of ["title", "description", "benefit"]) text(feature[name]);
    for (const name of ["howTo", "requirements", "limitations"])
      strings(feature[name]);
  }
  // All remaining leaf values are public single-line text, safe to include in a Markdown brief.
  function plain(value) {
    if (typeof value === "string") {
      assert(
        value.length <= 8000 && !/[<>\u0000-\u001f]/u.test(value),
        "Invalid public text",
      );
    } else if (Array.isArray(value)) {
      assert(value.length <= 100);
      value.forEach(plain);
    } else if (value && typeof value === "object")
      Object.values(value).forEach(plain);
    else assert(value === null || typeof value === "number");
  }
  plain(feed);
  return feed;
}

function review(feed, previous) {
  const before = new Map(
    (previous?.features ?? []).map((feature) => [feature.id, feature]),
  );
  const changes = feed.features.filter(
    (feature) => json(feature) !== json(before.get(feature.id)),
  );
  const removed = [...before.values()].filter(
    (feature) => !feed.features.some((next) => next.id === feature.id),
  );
  return [
    "# Bon Plot — предложение обновления сведений сайта",
    "",
    `Редакция: ${feed.revision}. Обновлено: ${feed.updatedAt}. Утверждение: ${feed.publication.status}.`,
    `Опубликованная программа: ${feed.release.latestPublished}.`,
    "",
    "Это автоматически подготовленная сверка фактов. Рекламные тексты и статьи не переписывались.",
    "",
    "## Изменившиеся возможности",
    "",
    ...changes.flatMap((feature) => [
      `### ${feature.title}`,
      "",
      `Статус: ${before.get(feature.id)?.availability ?? "отсутствовала в паспорте"} → ${feature.availability}.`,
      `Было: ${before.get(feature.id)?.description ?? "Не описано."}`,
      `Стало: ${feature.description}`,
      `Польза: ${feature.benefit}`,
      "",
      ...feature.requirements.map((item) => `- Условие: ${item}`),
      ...feature.limitations.map((item) => `- Ограничение: ${item}`),
      "",
    ]),
    ...removed.map(
      (feature) =>
        `- Удалено из паспорта: ${feature.title}. Проверить старые упоминания на сайте.`,
    ),
    "",
    "## Задание агенту сайта",
    "",
    "- Сверить /plot/, FAQ, описания и связанные статьи с public/product-info/bon-plot.json.",
    "- Проверить также общие ограничения, версии и аудитории: они могут измениться без изменения карточек.",
    "- Описывать только возможности, подтверждённые в указанном опубликованном выпуске.",
    "- Сохранить условия и ограничения. Не усиливать обещания AI и не выдумывать результаты проверок.",
    "- Следовать CONTENT_SPEC.md и editorial/STYLE_GUIDE.md; статьи требуют отдельного задания и проверки.",
    "- Подготовить правки для владельца. Публикация рекламных текстов и статей этим заданием не разрешена.",
    "",
  ].join("\n");
}

async function optional(path) {
  try {
    return await readFile(path, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

export async function syncCatalog(sourceRoot, siteRoot, mode = "write") {
  assert(["write", "check", "review"].includes(mode));
  const source = resolve(sourceRoot, "docs/product/generated");
  const files = {};
  for (const name of ["bon-plot.json", "bon-plot.md", "manifest.json"]) {
    const raw = await readFile(resolve(source, name));
    assert(raw.length <= 512 * 1024, "Catalog package is too large");
    files[name] = raw.toString("utf8");
  }
  const feed = validatePublicFeed(
    JSON.parse(files["bon-plot.json"]),
    JSON.parse(files["manifest.json"]),
    files,
  );
  const target = resolve(siteRoot, "public/product-info");
  const previousText = await optional(resolve(target, "bon-plot.json"));
  const previous = previousText === null ? null : JSON.parse(previousText);
  if (previous) {
    assert(feed.revision >= previous.revision, "Catalog revision rollback");
    assert(feed.updatedAt >= previous.updatedAt, "Catalog date rollback");
    if (feed.revision === previous.revision)
      assert.equal(
        feed.publication.contentHash,
        previous.publication.contentHash,
        "Increment catalog revision before changing facts",
      );
  }
  const approved = feed.publication.status === "approved";
  const changed =
    approved &&
    (
      await Promise.all(
        ["bon-plot.json", "bon-plot.md"].map(
          async (name) =>
            (await optional(resolve(target, name))) !== files[name],
        ),
      )
    ).some(Boolean);
  if (mode === "review" || (mode === "write" && changed)) {
    const path = resolve(siteRoot, "editorial/product-updates/bon-plot.md");
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, review(feed, previous), "utf8");
  }
  if (mode === "write" && changed) {
    await mkdir(target, { recursive: true });
    for (const name of ["bon-plot.json", "bon-plot.md"])
      await writeFile(resolve(target, name), files[name], "utf8");
  }
  return {
    approved,
    changed,
    revision: feed.revision,
    contentHash: feed.publication.contentHash,
  };
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const args = process.argv.slice(2);
  assert(
    args[0] === "--source" && args[1] && args.length <= 3,
    "Use --source PROJECT_DIRECTORY [--check|--review]",
  );
  assert(!args[2] || ["--check", "--review"].includes(args[2]));
  const result = await syncCatalog(
    args[1],
    fileURLToPath(new URL("..", import.meta.url)),
    args[2]?.slice(2) ?? "write",
  );
  console.log(JSON.stringify(result));
  if (!result.approved)
    console.log("Source catalog is a draft: public files were not changed.");
  if (process.env.GITHUB_OUTPUT)
    await writeFile(
      process.env.GITHUB_OUTPUT,
      `changed=${result.changed}\ncontent_hash=${result.contentHash}\n`,
      { flag: "a" },
    );
}
