import test from "node:test";
import assert from "node:assert/strict";
import {checkoutPayload,checkoutAmount,product} from "../lib/checkout.mjs";
test("checkout uses the product amount in cents",()=>assert.equal(checkoutAmount(product),4900));
test("checkout payload is valid for Stripe test mode",()=>assert.deepEqual(checkoutPayload(),{amount:4900,currency:"usd",name:"The Focus Kit"}));
