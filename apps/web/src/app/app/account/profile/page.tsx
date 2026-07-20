import { ProfileForm } from "@/components/account/ProfileForm";
import { requireSession } from "@/lib/auth";

export default async function ProfilePage() {
  const user = await requireSession();
  return <ProfileForm user={user} />;
}
