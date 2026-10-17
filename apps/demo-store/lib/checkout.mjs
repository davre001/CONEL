export const product = {
  id: "conel-desk-kit",
  name: "The Focus Kit",
  amount: 4900,
  currency: "usd",
};
export function checkoutAmount(item) {
  return item.amount;
}
export function checkoutPayload() {
  const amount = checkoutAmount(product);
  if (!Number.isInteger(amount) || amount <= 0)
    throw new Error(
      "Checkout amount must be a positive integer; inspect lib/checkout.mjs",
    );
  return { amount, currency: product.currency, name: product.name };
}
