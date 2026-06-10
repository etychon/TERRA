import { formatSince } from "./timeUtils";

type Props = { iso: string; reachability: string };

export function StatusSinceCell({ iso, reachability }: Props) {
  return <span>{formatSince(iso, reachability)}</span>;
}
