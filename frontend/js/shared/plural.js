/** Русские числительные: «1 вариант», «2 варианта», «5 вариантов». */
export function plural(count, one, few, many) {
  const number = Math.abs(Math.trunc(count));
  const lastTwo = number % 100;
  if (lastTwo >= 11 && lastTwo <= 14) return many;
  const last = number % 10;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}

/** То же, но сразу с числом: «5 вариантов». */
export function pluralize(count, one, few, many) {
  return `${count} ${plural(count, one, few, many)}`;
}
