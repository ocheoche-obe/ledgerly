import { useState } from "react";
import type { Api, Category } from "./api";
import { styles } from "./styles";

// Category management (FR-4.1): create, rename, archive/unarchive. The starter set (FR-4.4)
// is seeded server-side on first load, so this panel just reflects and edits whatever the
// API returns. Transaction reassignment on archive (FR-4.5) arrives in Slice 7 — here,
// archive only flips status.
export function CategoriesPanel({
  api,
  categories,
  onChange,
  onError,
}: {
  api: Api;
  categories: Category[];
  onChange: (c: Category[]) => void;
  onError: (e: string) => void;
}) {
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  const replace = (updated: Category) =>
    onChange(
      categories
        .map((c) => (c.categoryId === updated.categoryId ? updated : c))
        .sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name)),
    );

  const add = async () => {
    onError("");
    if (!newName.trim()) return;
    setBusy(true);
    try {
      const created = await api.createCategory(newName);
      onChange([...categories, created]);
      setNewName("");
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const rename = async (cat: Category) => {
    const next = window.prompt("Rename category", cat.name);
    if (next == null || next.trim() === cat.name) return;
    onError("");
    try {
      replace(await api.updateCategory(cat.categoryId, { name: next }));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleArchive = async (cat: Category) => {
    onError("");
    const status = cat.status === "active" ? "archived" : "active";
    try {
      replace(await api.updateCategory(cat.categoryId, { status }));
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section style={styles.card}>
      <h2 style={styles.sectionTitle}>Categories</h2>

      <div style={styles.row}>
        <input
          style={styles.input}
          placeholder="New category name"
          value={newName}
          aria-label="New category name"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <button style={styles.button} onClick={add} disabled={busy || !newName.trim()}>
          Add
        </button>
      </div>

      <ul style={styles.list}>
        {categories.map((cat) => (
          <li key={cat.categoryId} style={styles.listItem}>
            <span
              style={{
                ...styles.itemName,
                ...(cat.status === "archived" ? { color: "#999", textDecoration: "line-through" } : {}),
              }}
            >
              {cat.name}
            </span>
            {cat.status === "archived" && <span style={styles.badge}>archived</span>}
            <button style={styles.buttonGhost} onClick={() => rename(cat)}>
              Rename
            </button>
            <button style={styles.buttonGhost} onClick={() => toggleArchive(cat)}>
              {cat.status === "active" ? "Archive" : "Restore"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
