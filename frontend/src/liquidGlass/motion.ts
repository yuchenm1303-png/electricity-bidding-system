export type SpringValue = { value: number; velocity: number; target: number };

/**
 * Exact solution of x'' + damping*x' + stiffness*(x-target) = 0.
 * Unlike explicit Euler, the same transition remains stable at 30/60/144 Hz
 * and on the first frame after the browser resumes a background tab.
 */
export function stepSpring(spring: SpringValue, dt: number, stiffness: number, damping: number) {
  const t = Math.max(0, Math.min(Number.isFinite(dt) ? dt : 0, 0.064));
  if (!t) return;
  const omega = Math.sqrt(Math.max(1, stiffness));
  const gamma = Math.max(0, damping) / 2;
  const displacement = spring.value - spring.target;
  const velocity = spring.velocity;
  let nextPosition: number;
  let nextVelocity: number;
  if (Math.abs(gamma - omega) < 0.0001) {
    const a = velocity + gamma * displacement;
    const decay = Math.exp(-gamma * t);
    nextPosition = (displacement + a * t) * decay;
    nextVelocity = (velocity - gamma * a * t) * decay;
  } else if (gamma < omega) {
    const frequency = Math.sqrt(omega * omega - gamma * gamma);
    const decay = Math.exp(-gamma * t);
    const sine = Math.sin(frequency * t);
    const cosine = Math.cos(frequency * t);
    const b = (velocity + gamma * displacement) / frequency;
    nextPosition = decay * (displacement * cosine + b * sine);
    nextVelocity = decay * (velocity * cosine - (gamma * velocity + omega * omega * displacement) * sine / frequency);
  } else {
    // Overdamped spring: use stable characteristic roots, without cancellation
    // in the nearly critical case handled by the branch above.
    const discriminant = Math.sqrt(gamma * gamma - omega * omega);
    const r1 = -gamma + discriminant;
    const r2 = -gamma - discriminant;
    const a = (velocity - r2 * displacement) / (r1 - r2);
    const b = displacement - a;
    nextPosition = a * Math.exp(r1 * t) + b * Math.exp(r2 * t);
    nextVelocity = a * r1 * Math.exp(r1 * t) + b * r2 * Math.exp(r2 * t);
  }
  spring.value = spring.target + nextPosition;
  spring.velocity = nextVelocity;
}

export function springSettled(spring: SpringValue, positionTolerance = 0.002, velocityTolerance = 0.02) {
  return Math.abs(spring.target - spring.value) < positionTolerance &&
    Math.abs(spring.velocity) < velocityTolerance;
}
