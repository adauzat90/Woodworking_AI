import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

// Saved cabinet designs. `spec` is the furniture-DSL JSON object as produced by
// the Python engine; we store it opaquely so the schema never has to track the
// DSL's evolution.
export default defineSchema({
  designs: defineTable({
    name: v.string(),
    spec: v.any(),
    createdAt: v.number(),
  }).index("by_createdAt", ["createdAt"]),

  // A revision history: each save of a named design appends a snapshot, so a
  // user can review and compare earlier versions of the same piece.
  revisions: defineTable({
    name: v.string(),       // the design name this revision belongs to
    spec: v.any(),          // the furniture-DSL JSON at this revision
    note: v.optional(v.string()),
    createdAt: v.number(),
  }).index("by_name_createdAt", ["name", "createdAt"]),
});
