import { formatLocalSync } from "./timeUtils";

type Props = { iso: string };

export function LocalTimeCell({ iso }: Props) {
  return <span>{formatLocalSync(iso)}</span>;
}
