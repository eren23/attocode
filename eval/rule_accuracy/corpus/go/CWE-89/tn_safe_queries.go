// SQL — true negatives (safe patterns)
// no-expect: These should NOT trigger SQL injection rules
package corpus

import "database/sql"

func safeParameterized(db *sql.DB, userID string) {
	db.Query("SELECT * FROM users WHERE id = ?", userID)
}

func safePrepared(db *sql.DB, name string) {
	stmt, _ := db.Prepare("SELECT * FROM users WHERE name = ?")
	stmt.Query(name)
}

func safeConstant(db *sql.DB) {
	db.Query("SELECT count(*) FROM users")
}
