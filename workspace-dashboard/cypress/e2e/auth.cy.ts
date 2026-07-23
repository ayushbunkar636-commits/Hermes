describe('Authentication Flow', () => {
  it('redirects unauthenticated users to login', () => {
    cy.visit('/');
    cy.url().should('include', '/login');
  });

  it('allows user to type into login form', () => {
    cy.visit('/login');
    cy.get('input[type="email"]').type('admin@hermes.com');
    cy.get('input[type="password"]').type('admin123');
    cy.get('button[type="submit"]').contains('Sign In');
  });
});
