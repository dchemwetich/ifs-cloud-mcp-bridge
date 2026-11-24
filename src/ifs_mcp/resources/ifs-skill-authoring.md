# IFS Skill Authoring Guide

How to create, build, format and save a new IFS skill (resource guide) from a projection, OpenAPI spec or HAR file. Use when no existing guide covers the user's workflow.

Use the `call_protected_api` tool with the endpoints below to interact with IFS Cloud.

---

## Skill file format

Every skill must follow this structure exactly:

```markdown
# [Guide Name]

[1–2 sentence description of what this guide enables.]

Use the `call_protected_api` tool with the endpoints below to [purpose].

## Base Path

All endpoints below are relative to this base:
```
/main/ifsapplications/projection/v1/[ServiceName].svc
```

---

## 1. [Operation Name]

[What this operation does in plain language.]

**Endpoint:**
```
/main/ifsapplications/projection/v1/[ServiceName].svc/[EntitySet]
```

**Method:** GET | POST | PATCH | DELETE

**Useful fields for `$select`:**
`Field1`, `Field2`, `Field3`

**Examples:**

[Business-meaningful label]:
```
[example URL or request body]
```

**Response shape:**
```json
{ "value": [{ ... }] }
```

[Repeat for each operation]

---

## Recommended Workflows

[Numbered multi-step workflows combining calls]

> Before fetching large datasets, add `$count=true` to check result size. If results exceed 10 records, confirm with the user before fetching all data.

For OData query syntax, use `get_api_guide({ guide: "ifs-common-odata-reference" })`.
```

---

## Saving the skill

1. Ask the user: "What should the filename be? Use the format `ifs-[module]-[area]`, e.g. `ifs-sales-customers` - saved as .md". If updating an existing skill, use its current filename.
2. Call `save_skill({ filename: "...", content: "..." })` to save it.
3. Check the result:
   - `action: "created"` - confirm the skill is saved and available via `get_api_guide`. No restart needed.
   - `action: "updated"` - show the `changes` summary so the user can see what changed.
   - Error - report it and ask the user to check the filename or path.
4. After saving, others can import the skill with `import_skill({ source: "HTTPS URL to the .md file" })`.

---

## Write-call gotchas to document in skills

Note these in any skill that creates or changes data, next to the operation they affect.

### Date/time values in write bodies

In POST/PATCH bodies and action parameters, send date/time values as **local IFS server time with no timezone suffix**: `"2026-05-18T10:00:00"`, not `"2026-05-18T10:00:00Z"` or `"...+03:00"`. Values sent with a suffix have been seen to land hours off and fail validation (for example `WRNGSTARTTIME`, "cannot be a future time", on shop floor clockings). Timestamps in responses may carry a `Z` - don't assume they are UTC; compare one with what the IFS client shows for the same record before converting anything. If unsure of the server's time zone, ask the user.

### ODP_DESERIALIZATION_ERROR

IFS could not read the request body: a field has the wrong JSON type or format. Check, in this order:

1. **Field types in the spec** - `read_openapi_file` (or the live spec) lists each field's type. A field typed `string` must be sent as a JSON string even when it looks like a boolean or number: `...Db` flags such as `RentalDb` take `"TRUE"`/`"FALSE"`, not `true`/`false`.
2. **How the IFS client sends it** - record the same action in the browser and run `parse_har_file`. The recorded body shows the exact field names and shape. The browser sends numbers as strings (`IEEE754Compatible=true`), so take the type from the spec, not the recording.
3. **Date formats** - `Edm.Date` takes `"2026-05-18"`, `Edm.DateTimeOffset` a full timestamp (see above).

Document the corrected type in the skill so the next call gets it right first time.

### Warnings (X-IFS-Accept-Warnings)

Some IFS writes raise a warning that the IFS client shows as an OK/Cancel question (for example `INVALSHIPDATE` when a planned ship date is in the past). Through the API it comes back as an error unless the request carries `X-IFS-Accept-Warnings: true`.

- In the skill, list the warnings an operation is known to raise and what they mean.
- Never tell the agent to send the header by default. The call is made without it first; the agent shows the user the warning and repeats the call with the header only if the user agrees - the same choice the IFS client would have asked them to make.

---

## HAR mode guidelines

When building from a HAR file:

- Work through one projection service at a time
- For each operation (entity set + method), ask the user what it represents in their workflow
- Replace all real data values with realistic placeholders (e.g. `CUST-001`, `PO-10001`, `2024-01-15`)
- Preserve IfsApp enum values exactly as seen - they are structural, not sensitive
- Only include operations and filter patterns the user confirms are useful
- Ask at most 2 questions at a time and use the user's own words in descriptions

---

## OpenAPI mode guidelines

When building from an OpenAPI/Swagger spec (downloaded file or live fetch):

- Not everything in the spec needs to go into the skill - work selectively
- For each relevant entity set, ask the user what it represents in their business
- Derive realistic placeholder values matching field type and maxLength
- Suggest common `$filter` patterns: `contains(Name,'{value}')` for strings, `eq '{value}'` for key fields
- For POST/PATCH: document required fields clearly, list optional fields in a reference table
- Ask about multi-step workflows (e.g. create → validate → link to another entity)
- For enums: list all values with a short explanation (ask the user what each means)
- Ask at most 2 questions at a time and use the user's own words in descriptions
