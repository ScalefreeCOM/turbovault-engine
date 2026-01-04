"""
Integration tests for dbt project generation.
"""
import pytest
from pathlib import Path


class TestDbtProjectGenerator:
    """Integration tests for the DbtProjectGenerator class."""
    
    def test_generate_creates_folder_structure(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        generation_config,
        template_resolver
    ):
        """Generator creates correct folder structure."""
        from engine.services.generation import DbtProjectGenerator
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=generation_config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        # Check folder structure
        assert (temp_output_dir / "models" / "staging").exists()
        assert (temp_output_dir / "models" / "raw_vault").exists()
        assert (temp_output_dir / "models" / "business_vault").exists()
        assert (temp_output_dir / "models" / "control").exists()
        assert (temp_output_dir / "macros").exists()
        assert (temp_output_dir / "tests").exists()
    
    def test_generate_creates_project_files(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        generation_config,
        template_resolver
    ):
        """Generator creates dbt_project.yml and packages.yml."""
        from engine.services.generation import DbtProjectGenerator
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=generation_config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        assert (temp_output_dir / "dbt_project.yml").exists()
        assert (temp_output_dir / "packages.yml").exists()
        
        # Check dbt_project.yml content
        content = (temp_output_dir / "dbt_project.yml").read_text()
        assert generation_config.project_name in content
    
    def test_generate_creates_sources_yml(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        generation_config,
        template_resolver
    ):
        """Generator creates sources.yml in staging folder."""
        from engine.services.generation import DbtProjectGenerator
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=generation_config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        sources_yml = temp_output_dir / "models" / "staging" / "sources.yml"
        assert sources_yml.exists()
    
    def test_generate_creates_sql_and_yaml_pairs(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        generation_config,
        template_resolver
    ):
        """Every SQL model has a corresponding YAML file."""
        from engine.services.generation import DbtProjectGenerator
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=generation_config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        # Check that report has no YML_001 warnings (missing YAML files)
        yml_001_warnings = [w for w in report.warnings if w.code == "YML_001"]
        assert len(yml_001_warnings) == 0, f"Missing YAML files: {yml_001_warnings}"
    
    def test_generate_report_counts(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        generation_config,
        template_resolver
    ):
        """Report contains correct entity counts."""
        from engine.services.generation import DbtProjectGenerator
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=generation_config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        assert report.success
        assert report.stages_generated > 0
        assert report.hubs_generated > 0
        assert report.total_files > 0
    
    def test_generate_without_v1_satellites(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        template_resolver
    ):
        """Generator respects --no-v1-satellites option."""
        from engine.services.generation import DbtProjectGenerator, GenerationConfig
        
        config = GenerationConfig(
            project_name="test_project",
            generate_satellite_v1_views=False,
        )
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        assert report.satellite_views_generated == 0
    
    def test_generated_sql_contains_dbt_syntax(
        self,
        django_setup,
        project_export,
        temp_output_dir: Path,
        generation_config,
        template_resolver
    ):
        """Generated SQL files contain proper dbt Jinja syntax."""
        from engine.services.generation import DbtProjectGenerator
        
        generator = DbtProjectGenerator(
            output_path=temp_output_dir,
            config=generation_config,
            template_resolver=template_resolver
        )
        report = generator.generate(project_export)
        
        # Find SQL files from report (more reliable than glob)
        sql_files = [f for f in report.files if f.file_type == "sql"]
        assert len(sql_files) > 0, "Should have generated at least one SQL file"
        
        # Check that SQL contains dbt syntax (not TurboVault template syntax)
        content = sql_files[0].path.read_text()
        assert "{{" in content or "{%" in content, "Should contain dbt Jinja syntax"
        assert "[%" not in content, "Should not contain TurboVault template syntax"
        assert "[[" not in content, "Should not contain TurboVault template syntax"


class TestGenerationReport:
    """Tests for GenerationReport functionality."""
    
    def test_validate_yaml_files_detects_missing(self, django_setup):
        """validate_yaml_files adds warnings for missing YAML files."""
        from engine.services.generation.report import GenerationReport
        from pathlib import Path
        
        report = GenerationReport(project_path=Path("/test"))
        
        # Add SQL file without YAML
        report.add_file(Path("/test/hub.sql"), "hub_standard", "hub_customer", "sql")
        
        # Run validation
        report.validate_yaml_files()
        
        # Should have warning
        assert len(report.warnings) == 1
        assert report.warnings[0].code == "YML_001"
    
    def test_validate_yaml_files_passes_with_pairs(self, django_setup):
        """validate_yaml_files passes when SQL/YAML pairs exist."""
        from engine.services.generation.report import GenerationReport
        from pathlib import Path
        
        report = GenerationReport(project_path=Path("/test"))
        
        # Add SQL and YAML file pair
        report.add_file(Path("/test/hub.sql"), "hub_standard", "hub_customer", "sql")
        report.add_file(Path("/test/hub.yml"), "hub_standard", "hub_customer", "yaml")
        
        # Run validation
        report.validate_yaml_files()
        
        # Should have no warnings
        assert len(report.warnings) == 0
    
    def test_summary_format(self, django_setup):
        """Report summary is properly formatted."""
        from engine.services.generation.report import GenerationReport
        from pathlib import Path
        
        report = GenerationReport(project_path=Path("/test"))
        report.stages_generated = 5
        report.hubs_generated = 3
        
        summary = report.summary()
        
        assert "succeeded" in summary
        assert "Stages: 5" in summary
        assert "Hubs: 3" in summary
