// Product catalog search filters and keyword matching.
export function filterCatalog(items, query) { return items.filter(item => item.name.includes(query)); }
