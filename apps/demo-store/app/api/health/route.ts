import { checkoutPayload } from "../../../lib/checkout.mjs";
export const dynamic = "force-dynamic";
export function GET() {
  try {
    checkoutPayload();
    return Response.json({ status: "healthy", service: "CONEL Demo Store" });
  } catch {
    return Response.json(
      {
        status: "unhealthy",
        endpoint: "/api/checkout",
        message: "Checkout amount validation failed",
      },
      { status: 500 },
    );
  }
}
