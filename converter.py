# converter.py  (chỉ các phần thay đổi/đã thêm)

def convert_etsy_to_shopify(
    file_like_or_path,
    vendor_text: str = "",
    markup_pct: float = 0.0,
    variant_price_map: Dict[str, Any] | None = None,
    apply_markup_on_map: bool = False,
) -> pd.DataFrame:
    """
    Etsy CSV:
    - Bỏ 'Digital Download' trên mọi trục
    - SKU map theo Variation 1 (Option1) với token-matching
    - Nếu có variant_price_map: set giá theo Option1 (ưu tiên exact, rồi token), fallback dùng PRICE gốc + markup
    """
    etsy = pd.read_csv(file_like_or_path, engine="python")
    rows: List[Dict[str, Any]] = []

    # Chuẩn hoá price map (nếu có)
    def _norm_price(v):
        p = parse_price(v)
        return p if (p is not None and not (isinstance(p, float) and math.isnan(p))) else None

    map_exact = {}
    map_token = {}
    if variant_price_map:
        for k, v in variant_price_map.items():
            price_val = _norm_price(v)
            if price_val is None:
                continue
            k_str = str(k).strip()
            map_exact[k_str] = price_val
            # sinh token để match lỏng hơn
            tk = option1_token(k_str)
            if tk:
                map_token[tk] = price_val

    # Tiện ích lấy IMAGE1..IMAGE20
    image_cols = [c for c in etsy.columns if re.fullmatch(r"IMAGE\d{1,2}", str(c).upper())]
    if not image_cols:
        image_cols = [c for c in etsy.columns if "IMAGE" in str(c).upper()]

    for idx, r in etsy.iterrows():
        title = r.get("TITLE", "")
        desc = r.get("DESCRIPTION", "")
        price = r.get("PRICE", "")

        # Ảnh
        images = []
        for c in image_cols:
            v = r.get(c)
            if pd.notna(v) and str(v).strip():
                images.append(str(v).strip())
        images = images[:20]

        # Options
        opt1_name = r.get("VARIATION 1 NAME") or r.get("VARIATION 1 TYPE") or "Option1"
        opt2_name = r.get("VARIATION 2 NAME") or r.get("VARIATION 2 TYPE") or ""
        opt1_all  = split_list_field(r.get("VARIATION 1 VALUES"))
        opt2_all  = split_list_field(r.get("VARIATION 2 VALUES"))
        skus_all  = split_list_field(r.get("SKU"))

        # Lọc EXCLUDE_OPTIONS
        def keep(v): return str(v).strip().lower() not in EXCLUDE_OPTIONS
        opt1 = [v for v in opt1_all if keep(v)] or ["Default"]
        opt2 = [v for v in opt2_all if keep(v)]
        have_opt2 = len(opt2) > 0
        if len(opt1) == 0:
            continue

        # Map SKU theo Option1 (giống bản cũ)
        keep_mask1 = [keep(v) for v in opt1_all] if opt1_all else []
        if opt1_all and len(skus_all) == len(opt1_all):
            skus_by_pos = [s for s, k in zip(skus_all, keep_mask1) if k]
        else:
            skus_by_pos = skus_all[:len(opt1)]

        token_to_sku = {sku_token(s): s for s in skus_all}
        matched_skus: List[str] = []
        used = set()
        for i, o1 in enumerate(opt1):
            tok = option1_token(o1)
            sku = token_to_sku.get(tok)
            if sku is None:
                found = None
                for tk, val in token_to_sku.items():
                    if tk in tok or tok in tk:
                        if val not in used:
                            found = val; break
                sku = found
            if sku is None:
                sku = next((s for s in skus_by_pos if s not in used), "")
            used.add(sku)
            matched_skus.append(sku or f"ETSY-{slugify(title)}-{i+1:02d}")

        handle = slugify(title) or f"etsy-{idx+1}"
        vendor = vendor_text or r.get("VENDOR", "") or ""
        default_price = apply_markup(price, markup_pct)

        def base_row():
            return {
                "Handle": handle,
                "Vendor": vendor,
                "Published": DEFAULT_PUBLISHED,
                "Variant Inventory Tracker": DEFAULT_INVENTORY_TRACKER,
                "Variant Inventory Qty": DEFAULT_INVENTORY_QTY,
                "Variant Inventory Policy": DEFAULT_INVENTORY_POLICY,
                "Variant Fulfillment Service": DEFAULT_FULFILLMENT_SERVICE,
                "Variant Requires Shipping": DEFAULT_REQUIRES_SHIPPING,
                "Variant Taxable": DEFAULT_TAXABLE,
                "Status": DEFAULT_STATUS,
            }

        def resolve_variant_price(option1_value: str):
            # 1) exact match
            if option1_value in map_exact:
                p = map_exact[option1_value]
                return round(p * (1 + float(markup_pct)/100.0), 2) if apply_markup_on_map else round(p, 2)
            # 2) token match (11x14, 12x16, A3…)
            tok = option1_token(option1_value)
            if tok and tok in map_token:
                p = map_token[tok]
                return round(p * (1 + float(markup_pct)/100.0), 2) if apply_markup_on_map else round(p, 2)
            # 3) fallback sang giá chung
            return default_price

        v_idx = 0
        for i, (o1, o1_sku) in enumerate(zip(opt1, matched_skus)):
            vprice = resolve_variant_price(str(o1)) if variant_price_map else default_price
            if have_opt2:
                for o2 in opt2:
                    row = base_row()
                    if v_idx == 0:
                        row.update({"Title": title, "Body (HTML)": desc})
                        if images:
                            row["Image Src"] = images[0]; row["Image Position"] = 1
                    row.update({
                        "Option1 Name": str(opt1_name),
                        "Option1 Value": str(o1),
                        "Option2 Name": str(opt2_name) if opt2_name else "",
                        "Option2 Value": str(o2) if opt2_name else "",
                        "Variant SKU": str(o1_sku),
                        "Variant Price": vprice,
                    })
                    rows.append(row); v_idx += 1
            else:
                row = base_row()
                if v_idx == 0:
                    row.update({"Title": title, "Body (HTML)": desc})
                    if images:
                        row["Image Src"] = images[0]; row["Image Position"] = 1
                row.update({
                    "Option1 Name": str(opt1_name),
                    "Option1 Value": str(o1),
                    "Variant SKU": str(o1_sku),
                    "Variant Price": vprice,
                })
                rows.append(row); v_idx += 1

        # Ảnh bổ sung
        for pos, url in enumerate(images[1:], start=2):
            rows.append({"Handle": handle, "Image Src": url, "Image Position": pos})

    return _finalize(rows)
