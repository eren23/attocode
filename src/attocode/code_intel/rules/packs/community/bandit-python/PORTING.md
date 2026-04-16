# Porting checklist — bandit-python

Rules from bandit (https://github.com/PyCQA/bandit) are not YAML-defined upstream
and require manual porting. Each ported rule MUST include the
attribution comment header at the top of its YAML file:

```yaml
# Adapted from bandit rule '<original-id>'
# See ../LICENSE and ../NOTICE for license terms.
```

Porting targets:

- [ ] B105 hardcoded_password_string
- [ ] B303 weak_md5_hash
- [ ] B304 weak_des_cipher
- [ ] B306 mktemp_temp_dir
- [ ] B307 use_of_eval
- [ ] B321 ftp_lib_used
- [ ] B324 weak_sha1_hash
- [ ] B501 request_with_no_cert_validation
- [ ] B602 subprocess_with_shell_true
- [ ] B608 hardcoded_sql_expressions
