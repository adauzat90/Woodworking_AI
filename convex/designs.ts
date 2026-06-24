import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

// Save a design (the spec is the furniture-DSL JSON object).
export const save = mutation({
  args: { name: v.string(), spec: v.any() },
  handler: async (ctx, { name, spec }) => {
    return await ctx.db.insert("designs", { name, spec, createdAt: Date.now() });
  },
});

// Most recent designs first.
export const list = query({
  args: {},
  handler: async (ctx) => {
    return await ctx.db.query("designs").withIndex("by_createdAt").order("desc").take(50);
  },
});

export const get = query({
  args: { id: v.id("designs") },
  handler: async (ctx, { id }) => await ctx.db.get(id),
});

export const remove = mutation({
  args: { id: v.id("designs") },
  handler: async (ctx, { id }) => {
    await ctx.db.delete(id);
  },
});
