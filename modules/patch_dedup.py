with open('dv_pipeline.py', encoding='utf-8') as f:
    content = f.read()

print(f"Lines before: {content.count(chr(10))}")
print(f"dedup already there: {'Remove intra-staging duplicates' in content}")

if 'Remove intra-staging duplicates' not in content:
    old = '''    promote_sql = (
        f"INSERT INTO {full_tgt} ({tgt_cols_sql}) "
        f"SELECT {src_cols_sql} FROM {full_stg} s "
        f"{not_exists_clause} {bad_ids_clause}"
    )'''
    new = '''    # Remove intra-staging duplicates — keep lowest _stg_row_id per UWI
    if mapped_pks:
        pk_src = mapped_pks[0][1]
        try:
            with engine.begin() as con:
                con.execute(text(
                    f"DELETE FROM {full_stg} WHERE [_stg_row_id] NOT IN "
                    f"(SELECT MIN([_stg_row_id]) FROM {full_stg} "
                    f"GROUP BY [{pk_src}])"
                ))
        except Exception:
            pass

    promote_sql = (
        f"INSERT INTO {full_tgt} ({tgt_cols_sql}) "
        f"SELECT {src_cols_sql} FROM {full_stg} s "
        f"{not_exists_clause} {bad_ids_clause}"
    )'''
    if old in content:
        content = content.replace(old, new, 1)
        print("Dedup patch applied")
    else:
        print("ERROR: promote_sql pattern not found")
        idx = content.find("promote_sql = (")
        print(repr(content[idx:idx+200]))

with open('dv_pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"Lines after: {content.count(chr(10))}")
print(f"dedup: {'Remove intra-staging duplicates' in content}")
