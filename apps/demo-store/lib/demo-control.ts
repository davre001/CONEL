import { timingSafeEqual } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
export async function control(request: Request, broken: boolean) {
  if (process.env.NODE_ENV !== "development")
    return Response.json(
      {
        detail: "Source failure injection is restricted to local development.",
      },
      { status: 403 },
    );
  const expected = process.env.CONEL_DEMO_ADMIN_KEY;
  const supplied =
    request.headers.get("authorization")?.replace(/^Bearer /, "") ?? "";
  if (
    !expected ||
    Buffer.byteLength(supplied) !== Buffer.byteLength(expected) ||
    !timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))
  )
    return Response.json(
      { detail: "Admin credential required" },
      { status: 401 },
    );
  const target = path.join(process.cwd(), "lib", "checkout.mjs");
  const source = await readFile(target, "utf8");
  const changed = broken
    ? source.replace("return item.amount;", "return item.invalidAmount;")
    : source.replace("return item.invalidAmount;", "return item.amount;");
  await writeFile(target, changed, "utf8");
  return Response.json({
    status: broken
      ? "Real source defect injected. Checkout and the health endpoint will fail after recompilation."
      : "Demo source manually reset.",
  });
}
