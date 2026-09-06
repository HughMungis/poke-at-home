class Gen5Spec(GameSpec):
    """Black/White structural rules; deliberately no ROM or RAM addresses.

    Party:
        Six slots remain, but serialized party records are 220 bytes, versus
        Gen 4's 236. Boxed records remain 136 bytes: an eight-byte header and
        four 32-byte blocks. Species and moves are little-endian 16-bit values;
        direct byte-address lists inherited from GameSpec are unsuitable.

    Encryption:
        Gen 5 retains Gen 4's block shuffling and XOR stream scheme. The
        checksum seeds the core stream; the personality value selects the
        block permutation and independently seeds the party-tail stream.
        A serialized encrypted record is not necessarily the representation
        exposed by a live RAM object. Runtime readers must establish that
        representation and take a coherent snapshot before decoding.

    Maps:
        Both DS generations use map/header identifiers rather than Gen 1's
        single-byte namespace or Gen 2's group/number pair. Gen 4 identifiers,
        map tables and coordinate layouts cannot be reused for Unova.
        Display-location names and map-matrix indices are not sufficient
        identities. The adapter must distinguish interiors and floors and
        normalize overworld coordinates into a consistent tile space.

    Badges:
        Black/White has eight Unova badge flags. This matches D/P/Pt's logical
        width, but differs from HG/SS's sixteen badges. Eight logical bits do
        not establish the containing RAM field's width or its location.
        Badge readers must extract the ownership mask from verified player
        data, not treat unrelated trainer or save-block bytes as badges.

    Evidence:
        [PK5 format](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/PKM/PK5.cs)
        [DS crypto](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/PKM/Util/PokeCrypto.cs)
        [BW badge data](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Saves/Substructures/Gen5/Misc5.cs)

    Coverage:
        [Black decompilation](https://github.com/squiddonaut/pokeblack) is not
        an equivalent of pret/pokered or pret/pokecrystal's mature, annotated
        disassemblies. Its existence does not supply a complete, verified
        Black/White RAM map, event catalogue or map atlas for this adapter.
        DS heaps, pointers and overlays also require runtime validation;
        save-file documentation alone cannot establish live object locations.
        Version, language and revision must be pinned before implementing
        the readers below.

    Synthetic subclasses can provide normalized snapshots to exercise all
    implemented observation paths before any ROM integration. This class
    must not be registered as a playable game in SPECS yet.
    """

    slug = "gen5"
    max_party_size = 6
    boxed_struct_size = 136
    party_struct_size = 220
    badge_bytes = 1
    cut_move_id = 15

    # Remove inherited numeric placeholders that could accidentally read RAM.
    party_count_addr = None
    party_struct_addr = None
    party_moves_offset = None
    party_species_addrs = None
    level_addrs = None
    hp_addrs = None
    max_hp_addrs = None
    opponent_level_addrs = None
    x_addr = None
    y_addr = None
    map_addr = None
    map_group_addr = None
    badges_addr = None
    in_battle_addr = None
    event_flags_start = None
    event_flags_end = None
    excluded_event_flags = None
    events_file = None
    required_events_file = None
    essential_maps = None
    world_factory = None

    def _party_snapshot(self, read_m):
        """Return active members as decoded mappings, excluding unused slots.

        Each mapping contains species, level, hp, max_hp and four moves.
        Values are integers; species, moves and HP retain their full widths.
        Include eggs as occupied party slots. Return all members from one
        coherent snapshot.

        A synthetic subclass can return these mappings directly. A runtime
        implementation must locate the party container, validate its count,
        and decode its actual representation. Do not assume that serialized
        record size is also the stride of an arbitrary runtime wrapper.
        """
        raise NotImplementedError(
            "Gen5 party reading needs a verified Black/White party-container "
            "resolver, count layout, runtime record representation and "
            "coherent snapshot/decryption implementation."
        )

    def _party(self, read_m):
        party = tuple(self._party_snapshot(read_m))
        if len(party) > self.max_party_size:
            raise ValueError("Gen5 party snapshot contains more than six members.")
        for member in party:
            if len(member["moves"]) != 4:
                raise ValueError("Gen5 party member must contain four move slots.")
        return party

    def party_count(self, read_m):
        return len(self._party(read_m))

    def party_species(self, read_m):
        """Six observation slots; unused slots are zero."""
        party = self._party(read_m)
        return [p["species"] for p in party] + [0] * (6 - len(party))

    def levels(self, read_m):
        """Use decoded party levels, with zero padding for unused slots."""
        party = self._party(read_m)
        return [p["level"] for p in party] + [0] * (6 - len(party))

    def read_hp(self, read_m, start):
        """Read an explicitly supplied, already decrypted LE 16-bit field.

        This is an endian primitive, not a way to bypass party decoding.
        """
        return read_m(start) | (read_m(start + 1) << 8)

    def hp_fraction(self, read_m):
        party = self._party(read_m)
        hp = sum(p["hp"] for p in party)
        maximum = sum(p["max_hp"] for p in party)
        return hp / max(maximum, 1)

    def knows_move(self, read_m, move_id):
        return any(move_id in p["moves"] for p in self._party(read_m))

    def _position_snapshot(self, read_m):
        """Return normalized (tile_x, tile_y, unique_map_id) atomically.

        The identifier must be hashable and stable across episodes. A scalar
        header ID is appropriate only after verifying that it distinguishes
        every coordinate space used by the adapter; otherwise use a tuple.
        """
        raise NotImplementedError(
            "Gen5 position reading needs a verified Black/White field-object "
            "resolver, map-header identity and coordinate/floor conversion."
        )

    def coords(self, read_m):
        x, y, identity = self._position_snapshot(read_m)
        hash(identity)
        return x, y, identity

    def map_id(self, read_m):
        return self.coords(read_m)[2]

    def _badge_mask(self, read_m):
        """Return only the eight Unova ownership bits, normalized to an int."""
        raise NotImplementedError(
            "Gen5 badge reading needs a verified Black/White player-data "
            "resolver and badge-field width, ownership mask and bit order."
        )

    def badge_bits(self, read_m):
        mask = self._badge_mask(read_m)
        if not isinstance(mask, int) or not 0 <= mask < 256:
            raise ValueError("Gen5 badge adapter must return an eight-bit mask.")
        # Preserve this module's MSB-first observation convention.
        return np.array(
            [(mask >> bit) & 1 for bit in range(7, -1, -1)],
            dtype=np.int8,
        )

    def badge_count(self, read_m):
        return int(self.badge_bits(read_m).sum())

    def in_battle(self, read_m):
        raise NotImplementedError(
            "Gen5 battle detection needs verified Black/White battle-context "
            "lifecycle/state semantics; a generic nonzero byte is insufficient."
        )

    def opponent_level(self, read_m):
        raise NotImplementedError(
            "Gen5 opponent levels need a verified battle roster and a policy "
            "for active opponents in single, double, triple and rotation battles."
        )

    @property
    def n_event_bits(self):
        raise NotImplementedError(
            "Gen5 event width needs a verified Black/White flag catalogue and "
            "observation selection; no contiguous Gen1-style span is assumed."
        )

    def event_bits(self, read_m):
        raise NotImplementedError(
            "Gen5 event observations need verified flag storage, selected flag "
            "identifiers and a stable observation ordering."
        )

    def event_popcount(self, read_m):
        return sum(self.event_bits(read_m))

    def excluded_event_count(self, read_m):
        raise NotImplementedError(
            "Gen5 event exclusions need a verified initial-state/progress "
            "policy; an empty exclusion list has not been established."
        )

    @property
    def map_progress(self):
        raise NotImplementedError(
            "Gen5 map progress needs verified Black/White map identities "
            "and an ordered critical-path table."
        )

    def world(self):
        raise NotImplementedError(
            "Gen5 exploration canvas needs verified map counts, coordinate "
            "bounds and floor handling, or a supplied collision-free World; "
            "Gen2 TiledWorld defaults are not validated for Unova."
        )
