class CrystalSpec(Gen2Spec):
    """Pokemon Crystal.

    Local file access failed; RAM declarations below use the supplied excerpts.
    Floating WRAMX sections do not establish absolute addresses without the
    matching build's symbol table. Unresolved fields deliberately remain None.
    """

    slug = "crystal"

    party_count_addr = None             # UNVERIFIED: resolve wPartyCount in the matching ROM's .sym.
    party_struct_addr = None            # UNVERIFIED: resolve wPartyMon1 in the matching ROM's .sym.
    party_struct_size = None            # UNVERIFIED: confirm wPartyMon2 - wPartyMon1 from party_struct expansion.
    party_moves_offset = None           # UNVERIFIED: confirm wPartyMon1Moves - wPartyMon1 from party_struct expansion.
    party_species_addrs = None          # UNVERIFIED: resolve wPartySpecies and confirm PARTY_LENGTH.
    level_addrs = None                  # UNVERIFIED: resolve wPartyMon1Level through wPartyMon6Level.
    hp_addrs = None                     # UNVERIFIED: resolve wPartyMon1HP through wPartyMon6HP; confirm big-endian storage.
    max_hp_addrs = None                 # UNVERIFIED: resolve wPartyMon1MaxHP through wPartyMon6MaxHP; confirm byte order.
    opponent_level_addrs = None         # UNVERIFIED: resolve wOTPartyMon1Level through wOTPartyMon6Level and verify population in battle.

    x_addr = None                       # UNVERIFIED: resolve wXCoord in the matching ROM's .sym.
    y_addr = None                       # UNVERIFIED: resolve wYCoord in the matching ROM's .sym.
    map_addr = None                     # UNVERIFIED: resolve wMapNumber in the matching ROM's .sym.
    map_group_addr = None               # UNVERIFIED: resolve wMapGroup in the matching ROM's .sym.

    badges_addr = None                  # UNVERIFIED: resolve wJohtoBadges (alias wBadges) in the matching ROM's .sym.
    badge_bytes = 2                     # wJohtoBadges followed by wKantoBadges; Gen2Spec's two-byte layout.
    in_battle_addr = None               # UNVERIFIED: resolve wBattleMode; its documented values are 0, 1, 2.
    event_flags_start = None            # UNVERIFIED: resolve wEventFlags in the matching ROM's .sym.
    event_flags_end = None              # UNVERIFIED: resolve wCurBox, immediately after wEventFlags, as the exclusive end.
    excluded_event_flags = None         # UNVERIFIED: audit wEventFlags initialization and event constants for non-progress flags.

    cut_move_id = None                  # UNVERIFIED: confirm CUT in the matching build's move constants.

    # Ordered critical path; the index IS the progress rank.
    # Revisited maps occur only once so map_progress retains their original rank.
    # Gym entries measure arrival, not leader defeat.
    # Pairs beyond the supplied excerpt were read from upstream:
    # [Map constants](https://raw.githubusercontent.com/pret/pokecrystal/master/constants/map_constants.asm)
    essential_maps = (
        0x1804,                         # NEW_BARK_TOWN (group 24, number 4)
        0x1805,                         # ELMS_LAB (group 24, number 5)
        0x1803,                         # ROUTE_29 (group 24, number 3)
        0x1A03,                         # CHERRYGROVE_CITY (group 26, number 3)
        0x1A01,                         # ROUTE_30 (group 26, number 1)
        0x1A0A,                         # MR_POKEMONS_HOUSE (group 26, number 10)
        0x1A02,                         # ROUTE_31 (group 26, number 2)
        0x1A0B,                         # ROUTE_31_VIOLET_GATE (group 26, number 11)
        0x0A05,                         # VIOLET_CITY (group 10, number 5)
        0x0301,                         # SPROUT_TOWER_1F (group 3, number 1)
        0x0302,                         # SPROUT_TOWER_2F (group 3, number 2)
        0x0303,                         # SPROUT_TOWER_3F (group 3, number 3)
        0x0A07,                         # VIOLET_GYM (group 10, number 7)
        0x0A01,                         # ROUTE_32 (group 10, number 1)
        0x0325,                         # UNION_CAVE_1F (group 3, number 37)
        0x0806,                         # ROUTE_33 (group 8, number 6)
        0x0807,                         # AZALEA_TOWN (group 8, number 7)
        0x0804,                         # KURTS_HOUSE (group 8, number 4)
        0x0328,                         # SLOWPOKE_WELL_B1F (group 3, number 40)
        0x0805,                         # AZALEA_GYM (group 8, number 5)
        0x0B16,                         # ILEX_FOREST_AZALEA_GATE (group 11, number 22)
        0x0334,                         # ILEX_FOREST (group 3, number 52)
        0x0B17,                         # ROUTE_34_ILEX_FOREST_GATE (group 11, number 23)
        0x0B01,                         # ROUTE_34 (group 11, number 1)
        0x0B02,                         # GOLDENROD_CITY (group 11, number 2)
        0x0B03,                         # GOLDENROD_GYM (group 11, number 3)
    )
    world_factory = TiledWorld
