# Porting checklist — gosec-go

Rules from gosec (https://github.com/securego/gosec) are not YAML-defined upstream
and require manual porting. Each ported rule MUST include the
attribution comment header at the top of its YAML file:

```yaml
# Adapted from gosec rule '<original-id>'
# See ../LICENSE and ../NOTICE for license terms.
```

Porting targets:

- [ ] G101 hardcoded_credentials
- [ ] G102 bind_to_all_interfaces
- [ ] G103 unsafe_block
- [ ] G201 sql_format_string
- [ ] G203 unescaped_template_data
- [ ] G304 file_path_inclusion
- [ ] G401 weak_des_or_rc4_crypto
- [ ] G402 tls_min_version
- [ ] G501 weak_md5_hash
- [ ] G505 weak_sha1_hash
