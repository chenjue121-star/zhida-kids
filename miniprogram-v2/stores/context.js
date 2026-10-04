function createContextStore() {
  let epoch = 0;
  let current = null;
  return {
    select(value) { current = value ? Object.freeze({ ...value }) : null; epoch += 1; return epoch; },
    capture() { return { epoch, current }; },
    isCurrent(ticket) { return ticket.epoch === epoch; },
    clear() { current = null; epoch += 1; }
  };
}
module.exports = { createContextStore };
