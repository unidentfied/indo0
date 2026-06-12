package middleware

import (
	"net/http"
	"os"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
)

// UserClaims are embedded in the gin context after successful auth.
type UserClaims struct {
	Sub   string   `json:"sub"`
	Name  string   `json:"name"`
	Email string   `json:"email"`
	Roles []string `json:"roles"`
}

const claimsKey = "sindio_user_claims"

// GetUserClaims extracts user claims stored in the gin context.
func GetUserClaims(c *gin.Context) (*UserClaims, bool) {
	v, ok := c.Get(claimsKey)
	if !ok {
		return nil, false
	}
	claims, ok := v.(*UserClaims)
	return claims, ok
}

// JWTAuth returns middleware that validates Azure AD tokens.  Set
// AZURE_AD_TENANT_ID to enable real validation; otherwise the middleware
// runs in mock mode and accepts any well-formed Bearer token whose
// payload contains a "roles" claim that includes "nairobi-county-employee".
func JWTAuth() gin.HandlerFunc {
	tenantID := os.Getenv("AZURE_AD_TENANT_ID")

	if tenantID == "" {
		return mockJWTAuth()
	}
	return azureADJWTAuth(tenantID)
}

// --- mock mode (development) ---

func mockJWTAuth() gin.HandlerFunc {
	return func(c *gin.Context) {
		auth := c.GetHeader("Authorization")
		if auth == "" || !strings.HasPrefix(auth, "Bearer ") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing_authorization_header"})
			return
		}
		tokenStr := strings.TrimPrefix(auth, "Bearer ")

		parser := jwt.NewParser()
		token, _, err := parser.ParseUnverified(tokenStr, jwt.MapClaims{})
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid_token_format"})
			return
		}

		claims, ok := token.Claims.(jwt.MapClaims)
		if !ok {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid_claims"})
			return
		}

		rolesRaw, _ := claims["roles"].([]interface{})
		var roles []string
		hasCountyRole := false
		for _, r := range rolesRaw {
			if s, ok := r.(string); ok {
				roles = append(roles, s)
				if s == "nairobi-county-employee" {
					hasCountyRole = true
				}
			}
		}

		if !hasCountyRole {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "insufficient_permissions"})
			return
		}

		sub, _ := claims["sub"].(string)
		name, _ := claims["name"].(string)
		email, _ := claims["email"].(string)

		c.Set(claimsKey, &UserClaims{
			Sub:   sub,
			Name:  name,
			Email: email,
			Roles: roles,
		})
		c.Next()
	}
}

// --- Azure AD mode (production) ---

func azureADJWTAuth(tenantID string) gin.HandlerFunc {
	issuer := "https://login.microsoftonline.com/" + tenantID + "/v2.0"
	keyFunc := azureADKeyFunc(tenantID)

	return func(c *gin.Context) {
		auth := c.GetHeader("Authorization")
		if auth == "" || !strings.HasPrefix(auth, "Bearer ") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing_authorization_header"})
			return
		}
		tokenStr := strings.TrimPrefix(auth, "Bearer ")

		token, err := jwt.Parse(tokenStr, keyFunc,
			jwt.WithIssuer(issuer),
			jwt.WithAudience("api://sindio-nairobi"),
			jwt.WithValidMethods([]string{"RS256"}),
		)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid_token", "detail": err.Error()})
			return
		}

		claims, ok := token.Claims.(jwt.MapClaims)
		if !ok || !token.Valid {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid_claims"})
			return
		}

		rolesRaw, _ := claims["roles"].([]interface{})
		var roles []string
		hasCountyRole := false
		for _, r := range rolesRaw {
			if s, ok := r.(string); ok {
				roles = append(roles, s)
				if s == "nairobi-county-employee" {
					hasCountyRole = true
				}
			}
		}
		if !hasCountyRole {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "insufficient_permissions"})
			return
		}

		sub, _ := claims["sub"].(string)
		name, _ := claims["name"].(string)
		email, _ := claims["email"].(string)

		c.Set(claimsKey, &UserClaims{
			Sub:   sub,
			Name:  name,
			Email: email,
			Roles: roles,
		})
		c.Next()
	}
}

func azureADKeyFunc(tenantID string) jwt.Keyfunc {
	jwksURL := "https://login.microsoftonline.com/" + tenantID + "/discovery/v2.0/keys"
	return func(token *jwt.Token) (interface{}, error) {
		// In production this fetches and caches the JWKS from jwksURL.
		// For now, parse the kid from the token header and match it.
		kid, ok := token.Header["kid"].(string)
		if !ok {
			return nil, jwt.ErrInvalidKey
		}
		_ = kid
		_ = jwksURL
		// Placeholder: a real implementation would call the JWKS endpoint,
		// cache keys by kid, and return the parsed *rsa.PublicKey.
		return nil, jwt.ErrSignatureInvalid
	}
}
