"use client";

import type { ReactNode } from "react";
import ProfileProvider from "./ProfileProvider";
import RepresentativeActivity from "./RepresentativeActivity";

export default function ProfileExperience({ children }: { children: ReactNode }) {
  return <ProfileProvider renderActivity={scope => <RepresentativeActivity scope={scope} />}>{children}</ProfileProvider>;
}
