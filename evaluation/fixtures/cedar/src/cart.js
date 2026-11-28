// Shopping cart totals and checkout state; calculate taxes before payment.
export function cartTotal(prices) { return prices.reduce((sum, item) => sum + item, 0); }
