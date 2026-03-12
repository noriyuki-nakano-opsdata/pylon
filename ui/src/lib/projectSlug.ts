function normalizeProjectName(value: string): string {
  return value.normalize("NFKC").trim().toLowerCase();
}

export function slugifyProjectName(value: string): string {
  return normalizeProjectName(value)
    .replace(/['"]/g, "")
    .replace(/[\s._/]+/gu, "-")
    .replace(/[^\p{Letter}\p{Number}-]+/gu, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

export function createUniqueProjectSlug(
  name: string,
  existingSlugs: string[],
): string {
  const base = slugifyProjectName(name) || "project";
  const existing = new Set(existingSlugs.map((slug) => normalizeProjectName(slug)));

  if (!existing.has(normalizeProjectName(base))) {
    return base;
  }

  let index = 2;
  while (existing.has(normalizeProjectName(`${base}-${index}`))) {
    index += 1;
  }
  return `${base}-${index}`;
}
