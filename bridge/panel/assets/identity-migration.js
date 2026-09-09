/* U150 — migrate only MOT Deck-owned browser preferences before page boot.
   The new key is authoritative when both exist; old keys are always retired. */
(function migrateMOTDeckIdentityStorage() {
  try {
    Object.keys(localStorage).forEach(function (oldKey) {
      var newKey = oldKey.indexOf('harness.') === 0
        ? 'motdeck.' + oldKey.slice(8)
        : (oldKey.indexOf('harness-') === 0
            ? 'motdeck-' + oldKey.slice(8) : '');
      if (!newKey) return;
      if (localStorage.getItem(newKey) === null) {
        localStorage.setItem(newKey, localStorage.getItem(oldKey));
      }
      localStorage.removeItem(oldKey);
    });
  } catch (_) {
    /* Storage denial must not prevent a first-party page from booting. */
  }
}());
