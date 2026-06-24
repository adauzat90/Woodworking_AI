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
});
