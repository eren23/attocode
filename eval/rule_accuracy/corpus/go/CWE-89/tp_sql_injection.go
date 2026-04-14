// SQL injection patterns — true positives for rule accuracy testing
package corpus

import "database/sql"

func badSQLConcat(db *sql.DB, userID string) {
	db.Query("SELECT * FROM users WHERE id = '" + userID + "'") // expect: go-sql-string-concat
}

func badSQLSprintf(db *sql.DB, name string) {
	query := fmt.Sprintf("SELECT * FROM users WHERE name = '%s'", name)
	db.Query(query) // expect: go-sql-string-concat
}
