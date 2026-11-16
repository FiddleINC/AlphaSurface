// Labels and icons for the assistant modes (rules live in backend/brain/modes.py).

import { CheckCheck, GraduationCap, Handshake, MoonStar } from "lucide-react"

export const MODE_INFO = {
  tutor: {
    label: "Tutor", Icon: GraduationCap,
    blurb: "Hints and guiding questions. Never gives the answer away.",
  },
  checker: {
    label: "Checker", Icon: CheckCheck,
    blurb: "Only marks your work right or wrong. No solutions.",
  },
  collab: {
    label: "Collaborator", Icon: Handshake,
    blurb: "Answers, explains and adds ideas as you go.",
  },
  quiet: {
    label: "Quiet", Icon: MoonStar,
    blurb: "Stays out of the way until you ask with ? or your voice.",
  },
}

export const MODE_ORDER = ["tutor", "checker", "collab", "quiet"]
