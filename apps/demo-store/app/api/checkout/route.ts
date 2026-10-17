import { checkoutPayload } from "../../../lib/checkout.mjs";
export const dynamic = "force-dynamic";
export async function POST() {
  try {
    const payload = checkoutPayload();
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key?.startsWith("sk_test_"))
      return Response.json(
        { detail: "Configure a Stripe test-mode key before checkout." },
        { status: 503 },
      );
    const origin = process.env.DEMO_STORE_URL;
    if (!origin)
      return Response.json(
        { detail: "Demo Store URL is not configured." },
        { status: 503 },
      );
    const body = new URLSearchParams({
      mode: "payment",
      success_url: origin + "/success?session_id={CHECKOUT_SESSION_ID}",
      cancel_url: origin + "/",
      "line_items[0][quantity]": "1",
      "line_items[0][price_data][currency]": payload.currency,
      "line_items[0][price_data][unit_amount]": String(payload.amount),
      "line_items[0][price_data][product_data][name]": payload.name,
    });
    const response = await fetch(
      "https://api.stripe.com/v1/checkout/sessions",
      {
        method: "POST",
        headers: {
          Authorization: "Bearer " + key,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
        signal: AbortSignal.timeout(15000),
      },
    );
    if (!response.ok)
      throw new Error("Stripe test checkout rejected the request");
    const session = await response.json();
    return Response.json({ url: session.url });
  } catch (error) {
    if (
      process.env.CONEL_API_URL &&
      process.env.DEMO_STORE_PROJECT_ID &&
      process.env.DEMO_STORE_MONITOR_KEY
    ) {
      try {
        await fetch(process.env.CONEL_API_URL + "/api/monitor/error", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer " + process.env.DEMO_STORE_MONITOR_KEY,
          },
          body: JSON.stringify({
            project_id: process.env.DEMO_STORE_PROJECT_ID,
            error_name: "CheckoutFailure",
            message: "Checkout amount validation or Stripe request failed",
            stack: "lib/checkout.mjs: checkoutPayload",
            endpoint: "/api/checkout",
            method: "POST",
          }),
          signal: AbortSignal.timeout(5000),
        });
      } catch {
        /* Active health monitoring remains available. */
      }
    }
    return Response.json(
      {
        detail:
          error instanceof Error && error.message.includes("amount")
            ? "Checkout amount validation failed. Please try again after recovery."
            : "Checkout is unavailable. Please try again later.",
      },
      { status: 500 },
    );
  }
}
