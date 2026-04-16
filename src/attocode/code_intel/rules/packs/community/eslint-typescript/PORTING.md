# Porting checklist — eslint-typescript

Rules from eslint (https://github.com/eslint/eslint) are not YAML-defined upstream
and require manual porting. Each ported rule MUST include the
attribution comment header at the top of its YAML file:

```yaml
# Adapted from eslint rule '<original-id>'
# See ../LICENSE and ../NOTICE for license terms.
```

Porting targets:

- [ ] no-eval
- [ ] no-implied-eval
- [ ] no-new-func
- [ ] no-script-url
- [ ] no-return-await
- [ ] no-var
- [ ] prefer-const
- [ ] eqeqeq
- [ ] no-with
- [ ] no-throw-literal
