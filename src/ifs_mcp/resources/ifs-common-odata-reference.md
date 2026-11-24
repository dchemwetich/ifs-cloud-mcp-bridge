# IFS OData Query Reference

OData query syntax for IFS: $filter, $select, $orderby, $top, $expand, $count, paging and operators. Use when constructing or fixing query parameters for `call_protected_api` endpoints.

> Important: IFS Cloud requires double parentheses `((...))` around filter expressions. No space after comma in function calls like `startswith(tolower(Field),'text')`.

## Filter Operations

| Operation | Syntax | Example |
|-----------|--------|---------|
| Starts with (case-insensitive) | `((startswith(tolower(Field),'text')))` | `((startswith(tolower(Description),'sales')))` |
| Contains | `contains(Field,'text')` | `contains(Description,'order')` |
| Equals | `Field eq 'value'` | `CategoryId eq 'SALES'` |
| Not equals | `Field ne 'value'` | `Status ne 'CLOSED'` |
| Greater than | `Field gt value` | `Amount gt 1000` |
| Less than | `Field lt value` | `Amount lt 500` |
| AND | `expr1 and expr2` | `Status eq 'OPEN' and Amount gt 100` |
| OR | `expr1 or expr2` | `Status eq 'OPEN' or Status eq 'NEW'` |

## Filtering on Enum Fields

Enum fields (like `Objstate`, `SupplyCode`, `CatalogType`) require the fully qualified type name in the filter value. The format is:

```
Field eq Namespace.EnumType'Value'
```

The namespace follows the pattern `IfsApp.ProjectionName.EnumType`. Each projection guide lists the qualified names for its enum fields.

**Example - filter by order state:**
```
$filter=Objstate eq IfsApp.CustomerOrderHandling.CustomerOrderState'Released'
```

**Example - combine enum filters:**
```
$filter=Objstate eq IfsApp.CustomerOrderHandling.CustomerOrderState'Released' or Objstate eq IfsApp.CustomerOrderHandling.CustomerOrderState'Reserved'
```

> Important: Do NOT use plain string values like `Objstate eq 'Released'` for enum fields - this will return an error. Always use the fully qualified enum format.

## Query Parameters

| Parameter | Syntax | Example |
|-----------|--------|---------|
| Filter | `$filter=expr` | `$filter=((startswith(tolower(Description),'sales')))` |
| Select fields | `$select=F1,F2` | `$select=QuickReportId,Description` |
| Order ascending | `$orderby=Field asc` | `$orderby=QuickReportId asc` |
| Order descending | `$orderby=Field desc` | `$orderby=ModifiedDate desc` |
| Limit results | `$top=N` | `$top=10` |
| Skip results | `$skip=N` | `$skip=20` |
| Count results | `$count=true` | `$count=true` |

## Optimistic Concurrency (If-Match / ETag)

Many IFS entities reject an update or delete unless you prove you are changing the version you read.

1. GET the record. Each record carries an `@odata.etag` value, for example `W/"Vy8iQUFBVjJ5QUFHQUFBQkh6QUFBOjEi"`.
2. Send that exact value in the `If-Match` header on the `PATCH`, `DELETE` or bound action:
   `headers: { "If-Match": "W/\"Vy8iQUFBVjJ5QUFHQUFBQkh6QUFBOjEi\"" }`
3. If the call returns `precondition_failed` (HTTP 412), the record was changed in IFS after you read it and nothing was saved. GET it again, show the user what changed, and retry with the new `@odata.etag` only if the user agrees.

> Important: Never retry a 412 with the same etag, never replace it with `If-Match: *`, and never drop the header to force the write - each of those overwrites someone else's change.

## Error Codes from call_protected_api

| `error` | HTTP | Meaning and what to do |
|---------|------|------------------------|
| `authentication_required` | 401 | Session missing or expired. Call `start_oauth`. |
| `permission_denied` | 403 | Signed in, but the IFS user has no permission for this projection or action. Do not log in again; tell the user which endpoint was refused so their IFS administrator can grant the permission set. |
| `precondition_failed` | 412 | Stale `If-Match` etag. See Optimistic Concurrency above. |
| `read_only_environment` | - | The environment is marked read-only and the call was not a GET. |
| `API call failed` | other | IFS's error body is in `message` and `details`. Read it before retrying. |
