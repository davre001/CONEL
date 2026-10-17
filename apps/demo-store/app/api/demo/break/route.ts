import { control } from "../../../../lib/demo-control";
export async function POST(request: Request) {
  return control(request, true);
}
