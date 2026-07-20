import { redirect } from "next/navigation";

export default function AccountIndex() {
  redirect("/app/account/profile");
}
