class Gen4Spec(GameSpec):
    """Generation 4 DS games: STRUCTURE ONLY.

    NO ADDRESSES ARE DECLARED HERE. Deriving game-, revision-, and runtime-specific
    locations is a LATER PHASE requiring verification against real memory.
    GameSpec's inherited address defaults are placeholders, not usable locations.
    This class establishes structural boundaries for synthetic-memory tests
    before a concrete game spec is connected to a real ROM.

    Party records occupy 236 bytes. Their boxed portion contains four 32-byte
    blocks, shuffled according to the personality value and encrypted by XOR
    with a checksum-seeded PRNG stream. Decoding requires reading the header,
    decrypting little-endian words, validating the checksum, and restoring the
    logical block order selected by the personality value. Species and move
    identifiers are 16-bit values, not the single bytes used by earlier specs.

    The party extension contains level and battle statistics and uses a separate
    personality-seeded encryption stream. Level is not in the four shuffled
    blocks: unshuffling those blocks alone does not recover it. Consequently,
    reading one raw byte at a fixed level offset, as Gen1Spec and Gen2Spec do,
    cannot reliably produce a level. A decoder must handle both the boxed data
    and the party extension, and distinguish encrypted records from records
    already decrypted by the game.

    Badges belong to structured trainer/save data. Diamond/Pearl/Platinum have
    eight badges; HeartGold/SoulSilver have sixteen. A generation-wide spec
    cannot assume either Gen 1's one-byte RAM field or Gen 2's two adjacent
    regional bytes. Concrete specs must supply the badge layout and ordering.

    Map identity comes from a wider map/header identifier in field/location
    state, not Gen 1's single byte or Gen 2's (group, number) pair. Resolving
    that state, reading coordinates at their proper widths, and choosing a
    unique map key require a concrete game's layout.

    Event flags are packed bits within structured save/script state, alongside
    distinct script variables. They are not a declared flat RAM interval here.
    A concrete spec must resolve the flag storage, its extent and bit ordering,
    and the event definitions and exclusions; script variables must not be
    counted as flags.
    """

    party_struct_size = 236
    party_block_count = 4
    party_block_size = 32

    def decode_party(self, read_m):
        """Return occupied members with level, species, moves, hp and max_hp."""
        raise NotImplementedError(
            "Gen 4 party decoding requires a party-container resolver, "
            "record encryption-state handling, checksum-seeded block decryption "
            "and checksum validation, personality-selected block unshuffling, "
            "and personality-seeded party-extension decryption."
        )

    def levels(self, read_m):
        return [member["level"] for member in self.decode_party(read_m)]

    def party_species(self, read_m):
        return [member["species"] for member in self.decode_party(read_m)]

    def party_count(self, read_m):
        raise NotImplementedError(
            "Gen 4 party count requires the concrete game's party-container "
            "resolver and count-field layout."
        )

    def knows_move(self, read_m, move_id):
        return any(
            move_id in member["moves"]
            for member in self.decode_party(read_m)
        )

    def read_hp(self, read_m, start):
        """Read a little-endian HP word from an already decoded buffer.

        This helper does not decrypt live party memory. Its caller must supply
        a decoded byte reader and the position of the decoded HP field.
        """
        return read_m(start) | (read_m(start + 1) << 8)

    def hp_fraction(self, read_m):
        party = self.decode_party(read_m)
        hp = sum(member["hp"] for member in party)
        maximum = max(sum(member["max_hp"] for member in party), 1)
        return hp / maximum

    def opponent_level(self, read_m):
        raise NotImplementedError(
            "Gen 4 opponent levels require a battle-state resolver and the "
            "active battler layout, including decoding if encrypted party "
            "records are used as the source."
        )

    def in_battle(self, read_m):
        raise NotImplementedError(
            "Gen 4 battle detection requires the concrete game's field/battle "
            "state resolver and state interpretation."
        )

    def map_id(self, read_m):
        raise NotImplementedError(
            "Gen 4 map identity requires a field/location-state resolver, "
            "the map/header identifier's width, and its identity semantics."
        )

    def coords(self, read_m):
        raise NotImplementedError(
            "Gen 4 coordinates require a field/location-state resolver, "
            "coordinate field widths and units, and a decoded map identity."
        )

    @property
    def n_badge_bits(self):
        raise NotImplementedError(
            "Gen 4 badge width requires a concrete title: eight badges for "
            "Diamond/Pearl/Platinum or sixteen for HeartGold/SoulSilver."
        )

    def badge_bits(self, read_m):
        raise NotImplementedError(
            "Gen 4 badge extraction requires a trainer/save-data resolver "
            "and the concrete title's badge-field layout and output ordering."
        )

    def badge_count(self, read_m):
        return sum(int(bit) for bit in self.badge_bits(read_m))

    @property
    def n_event_bits(self):
        raise NotImplementedError(
            "Gen 4 event width requires the concrete game's event-flag "
            "table extent, excluding script variables."
        )

    def event_bits(self, read_m):
        raise NotImplementedError(
            "Gen 4 event extraction requires a save/script-state resolver "
            "and the event-flag table layout, extent, and bit ordering."
        )

    def event_popcount(self, read_m):
        return sum(int(bit) for bit in self.event_bits(read_m))

    def excluded_event_count(self, read_m):
        raise NotImplementedError(
            "Gen 4 event exclusions require game-specific excluded flag IDs "
            "and their mapping into the decoded event-flag table."
        )

    def world(self):
        raise NotImplementedError(
            "Gen 4 world projection requires a concrete map atlas or a tiled "
            "world sized for the game's map count and coordinate dimensions."
        )
