---
name: "Bulk DB Audit"
description: "Audit MongoDB/Mongoose operations for performance anti-patterns. Use when reviewing backend code, optimizing DB calls, adding new CRUD endpoints, or investigating slow API responses. Detects loops with individual DB calls that should use bulkWrite, insertMany, updateMany, or $in queries."
---

# Bulk DB Audit

## What This Skill Does

Scans backend service files for MongoDB/Mongoose operations that run inside loops or process records one-by-one, and recommends bulk alternatives that reduce DB round-trips by 10-1000x.

## When to Use

- After creating or modifying a backend service with DB operations
- When an API endpoint is slow or times out
- During code review of any service that handles arrays/batches of data
- Before deploying features that process uploads, imports, or batch operations

## Quick Start

Run this audit on the backend:

```bash
# Find all for-loop DB calls in services
grep -rn 'for.*of\|forEach\|\.map(' backend/src --include="*.ts" -l | \
  xargs grep -l 'await.*\.\(find\|findOne\|create\|updateOne\|deleteOne\|save\)'
```

Then for each file found, apply the patterns below.

---

## Anti-Patterns to Detect

### Pattern 1: findOne in a loop (N+1 query)

**Bad** - N database calls:
```typescript
for (const record of records) {
  const doc = await this.model.findOne({ email: record.email });
  // process doc
}
```

**Good** - 1 database call:
```typescript
const emails = records.map(r => r.email);
const docs = await this.model.find({ email: { $in: emails } }).lean();
const docMap = new Map(docs.map(d => [d.email, d]));

for (const record of records) {
  const doc = docMap.get(record.email);
  // process doc
}
```

### Pattern 2: create/save in a loop

**Bad** - N inserts:
```typescript
for (const item of items) {
  await this.model.create({ ...item, creator: userId });
}
```

**Good** - 1 bulk insert:
```typescript
const docs = items.map(item => ({ ...item, creator: userId }));
await this.model.insertMany(docs, { ordered: false });
```

### Pattern 3: updateOne in a loop

**Bad** - N updates:
```typescript
for (const id of ids) {
  await this.model.updateOne({ _id: id }, { $set: { status: 'active' } });
}
```

**Good** - 1 bulk update:
```typescript
await this.model.updateMany(
  { _id: { $in: ids } },
  { $set: { status: 'active' } }
);
```

### Pattern 4: Insert-or-update (upsert) in a loop

**Bad** - N upserts:
```typescript
for (const record of records) {
  await this.model.updateOne(
    { email: record.email, provider: record.provider },
    { $set: record },
    { upsert: true }
  );
}
```

**Good** - 1 bulkWrite:
```typescript
const bulkOps = records.map(record => ({
  updateOne: {
    filter: { email: record.email, provider: record.provider },
    update: { $set: record },
    upsert: true,
  },
}));
const result = await this.model.bulkWrite(bulkOps, { ordered: false });
// result.upsertedCount = new records
// result.modifiedCount = updated records
```

### Pattern 5: deleteOne in a loop

**Bad** - N deletes:
```typescript
for (const id of idsToRemove) {
  await this.model.deleteOne({ _id: id });
}
```

**Good** - 1 bulk delete:
```typescript
await this.model.deleteMany({ _id: { $in: idsToRemove } });
```

---

## Step-by-Step Audit Process

### Step 1: Find candidate files

Search for service files that have loops with awaited DB operations:

```
Grep for: `await.*this\.\w+Model\.\(findOne\|create\|updateOne\|deleteOne\|save\)`
In files matching: `*.service.ts` or `*.ts` in backend/src
```

Cross-reference with files containing `for`, `forEach`, or `.map(` nearby.

### Step 2: Classify each occurrence

For each hit, determine:

| Question | If Yes |
|----------|--------|
| Is the DB call inside a for/forEach/map loop? | Candidate for bulk optimization |
| Does the loop process an array from user input (upload, import, batch)? | High priority - directly impacts response time |
| Does the loop process a fixed small set (2-3 items)? | Low priority - bulk adds complexity for no gain |
| Does each iteration depend on the previous result? | Cannot parallelize - consider pipeline instead |

### Step 3: Apply the right bulk pattern

| Current Pattern | Replacement | Mongoose Method |
|----------------|-------------|-----------------|
| `findOne` in loop | Batch lookup with `$in` | `Model.find({ field: { $in: values } })` |
| `create` in loop | Bulk insert | `Model.insertMany(docs, { ordered: false })` |
| `updateOne` in loop (same update) | Bulk update | `Model.updateMany({ _id: { $in: ids } }, update)` |
| `updateOne` in loop (different updates) | Bulk write | `Model.bulkWrite(ops, { ordered: false })` |
| `upsert` in loop | Bulk upsert | `Model.bulkWrite(ops)` with `upsert: true` |
| `deleteOne` in loop | Bulk delete | `Model.deleteMany({ _id: { $in: ids } })` |

### Step 4: Add chunking for large datasets

If the input array could exceed 1000 items, chunk it:

```typescript
const CHUNK_SIZE = 1000;
for (let i = 0; i < items.length; i += CHUNK_SIZE) {
  const chunk = items.slice(i, i + CHUNK_SIZE);
  // Run bulk operation on chunk
  await this.model.insertMany(chunk, { ordered: false });
}
```

This prevents MongoDB's 16MB document limit from being hit on very large batches.

### Step 5: Return meaningful counts

When replacing insert with upsert, track what happened:

```typescript
const result = await this.model.bulkWrite(ops, { ordered: false });
return {
  created: result.upsertedCount,
  updated: result.modifiedCount,
  total: ops.length,
};
```

---

## Checklist

After auditing, verify:

- [ ] No `findOne`/`findById` calls inside loops - use `find({ $in })` instead
- [ ] No `create`/`save` calls inside loops - use `insertMany` instead
- [ ] No `updateOne` calls inside loops - use `updateMany` or `bulkWrite` instead
- [ ] No `deleteOne` calls inside loops - use `deleteMany` instead
- [ ] Large arrays (1000+) are chunked before bulk operations
- [ ] Upsert operations use `bulkWrite` with dedup filter to prevent duplicates
- [ ] `{ ordered: false }` is used for independent operations (faster, one failure doesn't stop batch)
- [ ] Results return counts (created, updated, matched, notFound) for user feedback

## When NOT to Optimize

- Loop body has conditional logic that depends on previous iteration's DB result
- Loop processes 1-3 fixed items (overhead of bulk setup exceeds savings)
- Operation requires per-document middleware/hooks (Mongoose hooks don't fire on bulk ops)
- Transaction isolation requires sequential processing
